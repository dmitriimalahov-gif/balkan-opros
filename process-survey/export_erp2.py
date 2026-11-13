#!/usr/bin/env python3
"""Явный read-only экспорт Kodos для staging → DQ → publish в ERP №2."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import tempfile
from datetime import datetime, timezone
from typing import Any
from role_packs import role_coverage, role_key, role_keys, role_title


def _interview(row_id: str, raw_doc: str, created_at: str, updated_at: str) -> dict[str, Any]:
    doc = json.loads(raw_doc)
    respondent = doc.get("respondent") if isinstance(doc.get("respondent"), dict) else {}
    return {
        "id": str(doc.get("id") or row_id),
        "created_at": str(doc.get("createdAt") or created_at),
        "updated_at": str(doc.get("updatedAt") or updated_at),
        "status": str(doc.get("status") or "in_progress"),
        "department_code": str(doc.get("dept") or "other"),
        "role_key": role_key(doc),
        "role_keys": role_keys(doc),
        "role_title": role_title(doc, "ru"),
        "role_coverage": role_coverage(doc),
        "about": str(doc.get("about") or ""),
        "about_analysis": doc.get("aboutAnalysis") if isinstance(doc.get("aboutAnalysis"), dict) else {},
        "respondent": {
            "name": str(respondent.get("name") or doc.get("name") or ""),
            "position": str(respondent.get("position") or doc.get("position") or ""),
            "employee_ref": respondent.get("employee_ref") or doc.get("employee_ref"),
        },
        "language": str(doc.get("lang") or "ru"),
        "messages": doc.get("messages") if isinstance(doc.get("messages"), list) else [],
        "attachments": [
            {key: item.get(key) for key in (
                "id", "kind", "name", "mime", "size", "sha256", "url",
                "questionIndex", "messageIndex", "question", "createdAt",
            ) if item.get(key) is not None}
            for item in doc.get("attachments") or [] if isinstance(item, dict)
        ],
        "summary": doc.get("summary") if isinstance(doc.get("summary"), dict) else {},
    }


def _atomic_write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as temporary:
            temporary.write(content)
            temporary.flush()
            os.fsync(temporary.fileno())
        os.replace(temporary_name, path)
    except Exception:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise


def _knowledge(connection: sqlite3.Connection) -> list[dict[str, Any]]:
    exists = connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='knowledge_documents'").fetchone()
    if not exists:
        return []
    connection.row_factory = sqlite3.Row
    rows = connection.execute('SELECT * FROM knowledge_documents ORDER BY id').fetchall()
    items = []
    for row in rows:
        items.append({
            'interview_id': row['interview_id'], 'attachment_id': row['attachment_id'], 'status': row['status'],
            'source_name': row['source_name'], 'kind': row['source_kind'], 'mime': row['mime'], 'sha256': row['sha256'],
            'question_index': row['question_index'], 'message_index': row['message_index'],
            'role_keys': json.loads(row['role_keys'] or '[]'), 'department': row['department'],
            'position': row['position'], 'person_name': row['person_name'], 'language': row['language'],
            'analysis': json.loads(row['analysis_json'] or '{}'), 'extraction': json.loads(row['extraction_json'] or '{}'),
            'text': (row['extracted_text'] or '')[:100000], 'error': row['error'],
            'created_at': row['created_at'], 'updated_at': row['updated_at'],
        })
    return items


def export_database(
    database: Path | str,
    output: Path | str,
    *,
    exported_at: str | None = None,
) -> dict[str, Any]:
    database_path = Path(database).resolve()
    output_path = Path(output).resolve()
    connection = sqlite3.connect(f"{database_path.as_uri()}?mode=ro", uri=True)
    try:
        rows = connection.execute(
            "SELECT id, doc, created_at, updated_at FROM interviews ORDER BY created_at, id"
        ).fetchall()
        knowledge_items = _knowledge(connection)
    finally:
        connection.close()
    payload = {
        "schema": "kodos.process-survey.export",
        "version": "1",
        "exported_at": exported_at or datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "interviews": [_interview(*row) for row in rows],
        "knowledge_documents": knowledge_items,
    }
    content = (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    sha256 = hashlib.sha256(content).hexdigest()
    _atomic_write(output_path, content)
    sidecar = output_path.with_suffix(".sha256")
    _atomic_write(sidecar, f"{sha256}  {output_path.name}\n".encode("ascii"))
    return {"output": str(output_path), "sha256": sha256, "interview_count": len(rows),
            "knowledge_count": len(knowledge_items)}


def main() -> None:
    parser = argparse.ArgumentParser(description="Экспорт интервью Kodos в ERP №2 без доступа ERP к SQLite")
    parser.add_argument("--database", type=Path, default=Path(__file__).resolve().parent / "data" / "survey.db")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = export_database(args.database, args.output)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()

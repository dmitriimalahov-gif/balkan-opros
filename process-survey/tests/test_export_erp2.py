"""Проверка read-only экспорта Kodos в контракт ERP №2."""

import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from export_erp2 import export_database


class ExportErp2Test(unittest.TestCase):
    def test_export_excludes_token_and_writes_sha256(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = root / "survey.db"
            connection = sqlite3.connect(database)
            connection.execute(
                "CREATE TABLE interviews (id TEXT PRIMARY KEY, token_hash TEXT UNIQUE NOT NULL, "
                "doc TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)"
            )
            doc = {
                "id": "interview-1",
                "name": "Сотрудник",
                "dept": "mgmt",
                "position": "Роль",
                "lang": "ru",
                "status": "done",
                "messages": [{"role": "user", "text": "Ответ"}],
                "summary": {"processes": []},
                "employee_ref": "actor-1",
                "createdAt": "2026-11-01T08:00:00+02:00",
                "updatedAt": "2026-11-01T09:00:00+02:00",
            }
            connection.execute(
                "INSERT INTO interviews VALUES (?, ?, ?, ?, ?)",
                ("interview-1", "secret-token-hash", json.dumps(doc, ensure_ascii=False), doc["createdAt"], doc["updatedAt"]),
            )
            connection.commit()
            connection.close()

            output = root / "export.json"
            result = export_database(database, output, exported_at="2026-11-01T10:00:00+00:00")
            content = output.read_bytes()
            payload = json.loads(content)

            self.assertEqual(result["interview_count"], 1)
            self.assertEqual(payload["schema"], "kodos.process-survey.export")
            self.assertEqual(payload["version"], "1")
            self.assertNotIn("secret-token-hash", content.decode("utf-8"))
            self.assertNotIn("token_hash", content.decode("utf-8"))
            interview = payload["interviews"][0]
            self.assertEqual(interview["respondent"]["employee_ref"], "actor-1")
            self.assertEqual(interview["department_code"], "mgmt")
            self.assertEqual(interview["role_key"], "14")
            self.assertEqual(interview["role_keys"], ["14"])
            self.assertEqual(interview["role_title"], "Руководитель компании / CEO")
            self.assertEqual(interview["role_coverage"]["total"], 14)
            self.assertEqual(interview["role_coverage"]["asked"], 0)
            self.assertEqual(interview["about"], "")
            self.assertEqual(interview["about_analysis"], {})
            digest = hashlib.sha256(content).hexdigest()
            self.assertEqual(result["sha256"], digest)
            self.assertIn(digest, output.with_suffix(".sha256").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()

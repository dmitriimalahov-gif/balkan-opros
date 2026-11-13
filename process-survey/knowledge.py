#!/usr/bin/env python3
"""Локальный разбор вложений и база знаний Kodos."""
from __future__ import annotations

import csv
import json
import os
import re
import sqlite3
import subprocess
import tempfile
import threading
import time
import urllib.request
import zipfile
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

BASE = Path(__file__).resolve().parent
TERMINAL_STATUSES = {'ready', 'extracted', 'failed'}
MAX_TEXT = 1_000_000
MAX_MODEL_TEXT = 30_000


class KnowledgeError(Exception):
    pass


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z')


def connect(database):
    con = sqlite3.connect(database, timeout=30)
    con.row_factory = sqlite3.Row
    return con


def init_knowledge(database) -> None:
    with connect(database) as con:
        con.execute('''CREATE TABLE IF NOT EXISTS knowledge_documents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            interview_id TEXT NOT NULL,
            attachment_id TEXT UNIQUE NOT NULL,
            status TEXT NOT NULL,
            source_name TEXT NOT NULL,
            source_kind TEXT NOT NULL,
            mime TEXT NOT NULL DEFAULT '',
            sha256 TEXT NOT NULL DEFAULT '',
            question_index INTEGER,
            message_index INTEGER,
            role_keys TEXT NOT NULL DEFAULT '[]',
            department TEXT NOT NULL DEFAULT '',
            position TEXT NOT NULL DEFAULT '',
            person_name TEXT NOT NULL DEFAULT '',
            language TEXT NOT NULL DEFAULT 'ru',
            extracted_text TEXT NOT NULL DEFAULT '',
            extraction_json TEXT NOT NULL DEFAULT '{}',
            analysis_json TEXT NOT NULL DEFAULT '{}',
            error TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )''')
        con.execute('CREATE INDEX IF NOT EXISTS idx_knowledge_status ON knowledge_documents(status, id)')
        con.execute('CREATE INDEX IF NOT EXISTS idx_knowledge_interview ON knowledge_documents(interview_id)')
        con.execute('CREATE INDEX IF NOT EXISTS idx_knowledge_source ON knowledge_documents(source_name)')


def enqueue_knowledge(database, doc, item) -> None:
    timestamp = now_iso()
    with connect(database) as con:
        con.execute('''INSERT OR IGNORE INTO knowledge_documents (
            interview_id, attachment_id, status, source_name, source_kind, mime, sha256,
            question_index, message_index, role_keys, department, position, person_name, language,
            created_at, updated_at
        ) VALUES (?, ?, 'queued', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''', (
            doc['id'], item['id'], item.get('name') or 'Документ', item.get('kind') or 'file',
            item.get('mime') or '', item.get('sha256') or '', item.get('questionIndex'), item.get('messageIndex'),
            json.dumps(doc.get('roleKeys') or [doc.get('roleKey') or '00'], ensure_ascii=False),
            doc.get('dept') or 'other', doc.get('position') or '', doc.get('name') or '', doc.get('lang') or 'ru',
            timestamp, timestamp,
        ))


def sync_knowledge(database, doc) -> None:
    with connect(database) as con:
        for item in doc.get('attachments') or []:
            con.execute('''UPDATE knowledge_documents SET question_index=?, message_index=?, role_keys=?,
                department=?, position=?, person_name=?, language=?, updated_at=? WHERE attachment_id=?''', (
                item.get('questionIndex'), item.get('messageIndex'),
                json.dumps(doc.get('roleKeys') or [doc.get('roleKey') or '00'], ensure_ascii=False),
                doc.get('dept') or 'other', doc.get('position') or '', doc.get('name') or '', doc.get('lang') or 'ru',
                now_iso(), item.get('id'),
            ))


def delete_knowledge(database, interview_id) -> None:
    with connect(database) as con:
        con.execute('DELETE FROM knowledge_documents WHERE interview_id=?', (interview_id,))


def _clean_cell(value) -> str:
    if value is None:
        return ''
    text = re.sub(r'\s+', ' ', str(value)).strip()
    return text[:500]


def _table_extraction(name, fields, rows, metadata=None):
    clean_fields = [_clean_cell(field) for field in fields]
    lines = ['Таблица: ' + name]
    if clean_fields:
        lines.append('Поля: ' + ' | '.join(clean_fields))
    field_examples = []
    for index, field in enumerate(clean_fields):
        example = ''
        for row in rows:
            if index < len(row) and _clean_cell(row[index]):
                example = _clean_cell(row[index])
                break
        if field:
            field_examples.append({'name': field, 'description': 'Поле исходной таблицы', 'example': example})
    for number, row in enumerate(rows, 2):
        values = [_clean_cell(value) for value in row]
        if any(values):
            lines.append('Строка ' + str(number) + ': ' + ' | '.join(values))
    return '\n'.join(lines), field_examples, metadata or {}


def extract_xlsx(path):
    import openpyxl
    stream = open(path, 'rb')
    workbook = openpyxl.load_workbook(stream, read_only=True, data_only=False)
    texts, fields, tables = [], [], []
    for sheet in workbook.worksheets[:20]:
        rows = list(sheet.iter_rows(min_row=1, max_row=min(sheet.max_row or 1, 41), max_col=min(sheet.max_column or 1, 20), values_only=True))
        if not rows:
            continue
        header = list(rows[0]) if rows else []
        text, sheet_fields, _ = _table_extraction(sheet.title, header, rows[1:])
        formulas = []
        for row in sheet.iter_rows(min_row=1, max_row=min(sheet.max_row or 1, 41), max_col=min(sheet.max_column or 1, 20)):
            for cell in row:
                if cell.data_type == 'f':
                    formulas.append(cell.coordinate + ': ' + str(cell.value))
        if formulas:
            text += '\nФормулы: ' + '; '.join(formulas[:50])
        texts.append(text)
        fields.extend(sheet_fields)
        tables.append({'name': sheet.title, 'rows': sheet.max_row, 'columns': sheet.max_column, 'fields': sheet_fields})
    workbook.close()
    stream.close()
    if not texts:
        raise KnowledgeError('empty_table')
    return '\n\n'.join(texts), {'fields': fields[:100], 'tables': tables, 'parser': 'openpyxl'}


def extract_xls(path):
    import pandas as pd
    workbook = pd.ExcelFile(path, engine='xlrd')
    texts, fields, tables = [], [], []
    for sheet in workbook.sheet_names[:20]:
        frame = workbook.parse(sheet, nrows=40).iloc[:, :20].fillna('')
        text, sheet_fields, _ = _table_extraction(sheet, list(frame.columns), frame.values.tolist())
        texts.append(text)
        fields.extend(sheet_fields)
        tables.append({'name': sheet, 'fields': sheet_fields})
    if not texts:
        raise KnowledgeError('empty_table')
    return '\n\n'.join(texts), {'fields': fields[:100], 'tables': tables, 'parser': 'xlrd'}


def extract_csv_file(path):
    last_error = None
    for encoding in ('utf-8-sig', 'cp1251'):
        try:
            with open(path, encoding=encoding, newline='') as stream:
                sample = stream.read(8192)
                stream.seek(0)
                try:
                    dialect = csv.Sniffer().sniff(sample, delimiters=',;\t|')
                except csv.Error:
                    dialect = csv.excel
                rows = []
                for index, row in enumerate(csv.reader(stream, dialect)):
                    if index > 40:
                        break
                    rows.append(row)
            if not rows:
                raise KnowledgeError('empty_table')
            text, fields, _ = _table_extraction(Path(path).name, rows[0], rows[1:41])
            return text, {'fields': fields, 'tables': [{'name': Path(path).name, 'fields': fields}], 'parser': 'csv'}
        except UnicodeError as error:
            last_error = error
    raise KnowledgeError('csv_encoding') from last_error


def extract_pdf(path):
    from pypdf import PdfReader
    reader = PdfReader(path)
    pages = []
    for page in reader.pages[:30]:
        try:
            pages.append(page.extract_text() or '')
        except Exception:
            pages.append('')
    text = '\n\n'.join(pages).strip()
    parser = 'pypdf'
    if len(text) < 50:
        try:
            result = subprocess.run(['/opt/homebrew/bin/pdftotext', '-layout', path, '-'], capture_output=True, timeout=45)
            if result.returncode == 0:
                text = result.stdout.decode('utf-8', errors='replace').strip()
                parser = 'pdftotext'
        except (OSError, subprocess.TimeoutExpired):
            pass
    if len(text) < 50:
        text = ocr_pdf(path)
        parser = 'macOS Vision'
    return text, {'fields': [], 'tables': [], 'pages': len(reader.pages), 'parser': parser}


def extract_strict_docx(path):
    """Strict OOXML (purl.oclc.org), который python-docx не открывает."""
    def local(element):
        tag = element.tag if hasattr(element, 'tag') else element
        return tag.rsplit('}', 1)[-1]

    def paragraph_text(paragraph):
        return _clean_cell(' '.join(node.text or '' for node in paragraph.iter() if local(node.tag) == 't'))

    lines, fields = [], []
    with zipfile.ZipFile(path) as archive:
        root = ET.fromstring(archive.read('word/document.xml'))
        for header in sorted(name for name in archive.namelist() if re.fullmatch(r'word/header\d+\.xml', name)):
            header_root = ET.fromstring(archive.read(header))
            lines.extend(paragraph_text(node) for node in header_root.iter() if local(node.tag) == 'p' and paragraph_text(node))
        body = next(node for node in root.iter() if local(node.tag) == 'body')
        for child in body:
            if local(child.tag) == 'p':
                text = paragraph_text(child)
                if text:
                    lines.append(text)
            elif local(child.tag) == 'tbl':
                rows = []
                for row in (node for node in child if local(node.tag) == 'tr'):
                    cells = []
                    for cell in (node for node in row if local(node.tag) == 'tc'):
                        cells.append(' '.join(paragraph_text(node) for node in cell.iter() if local(node.tag) == 'p' and paragraph_text(node)))
                    rows.append(cells)
                if rows:
                    text, table_fields, _ = _table_extraction('Таблица Word', rows[0], rows[1:])
                    lines.append(text)
                    fields.extend(table_fields)
        for footer in sorted(name for name in archive.namelist() if re.fullmatch(r'word/footer\d+\.xml', name)):
            footer_root = ET.fromstring(archive.read(footer))
            lines.extend(paragraph_text(node) for node in footer_root.iter() if local(node.tag) == 'p' and paragraph_text(node))
    if not lines:
        raise KnowledgeError('empty_text')
    return '\n\n'.join(lines), {'fields': fields[:100], 'tables': [], 'parser': 'strict-ooxml'}


def extract_docx(path):
    try:
        import docx
        document = docx.Document(path)
    except Exception:
        return extract_strict_docx(path)
    lines = [p.text.strip() for p in document.paragraphs if p.text.strip()]
    fields = []
    for table in document.tables[:20]:
        rows = [[cell.text for cell in row.cells] for row in table.rows[:41]]
        if rows:
            text, table_fields, _ = _table_extraction('Таблица Word', rows[0], rows[1:])
            lines.append(text)
            fields.extend(table_fields)
    return '\n\n'.join(lines), {'fields': fields[:100], 'tables': [], 'parser': 'python-docx'}


def extract_doc(path):
    result = subprocess.run(['/usr/bin/textutil', '-convert', 'txt', '-stdout', path], capture_output=True, timeout=60)
    if result.returncode != 0:
        raise KnowledgeError('doc_read')
    return result.stdout.decode('utf-8', errors='replace'), {'fields': [], 'tables': [], 'parser': 'textutil'}


def ocr_image(path):
    result = subprocess.run(['/usr/bin/xcrun', 'swift', str(BASE / 'ocr_vision.swift'), path], capture_output=True, timeout=180)
    if result.returncode != 0:
        raise KnowledgeError('ocr_failed')
    return result.stdout.decode('utf-8', errors='replace').strip(), {'fields': [], 'tables': [], 'parser': 'macOS Vision'}


def ocr_pdf(path):
    with tempfile.TemporaryDirectory(prefix='knowledge-pdf-ocr-') as folder:
        prefix = str(Path(folder) / 'page')
        result = subprocess.run(['/opt/homebrew/bin/pdftoppm', '-f', '1', '-l', '3', '-scale-to', '1800', '-png', path, prefix], capture_output=True, timeout=90)
        if result.returncode != 0:
            raise KnowledgeError('pdf_ocr_failed')
        texts = []
        for image in sorted(Path(folder).glob('page-*.png')):
            text, _ = ocr_image(str(image))
            texts.append(text)
        return '\n\n'.join(texts).strip()


def google_csv_url(url):
    match = re.search(r'/spreadsheets/d/([a-zA-Z0-9_-]+)', url)
    if not match:
        raise KnowledgeError('invalid_google_sheet_url')
    return 'https://docs.google.com/spreadsheets/d/' + match.group(1) + '/export?format=csv'


def extract_google_sheet(url):
    request = urllib.request.Request(google_csv_url(url), headers={'User-Agent': 'KodosKnowledge/1'})
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            content_type = response.headers.get('Content-Type', '')
            if 'text/html' in content_type.lower():
                raise KnowledgeError('google_sheet_not_public')
            raw = response.read(5 * 1024 * 1024 + 1)
    except KnowledgeError:
        raise
    except Exception as error:
        raise KnowledgeError('google_sheet_not_public') from error
    if len(raw) > 5 * 1024 * 1024:
        raise KnowledgeError('google_sheet_too_large')
    with tempfile.NamedTemporaryFile(suffix='.csv') as temporary:
        temporary.write(raw)
        temporary.flush()
        text, extraction = extract_csv_file(temporary.name)
    extraction['parser'] = 'google_sheets_public_csv'
    return text, extraction


def extract_document(item, path):
    if item.get('kind') == 'link':
        text, extraction = extract_google_sheet(item.get('url') or '')
    else:
        extension = Path(item.get('name') or '').suffix.lower()
        if extension == '.xlsx':
            text, extraction = extract_xlsx(path)
        elif extension == '.xls':
            text, extraction = extract_xls(path)
        elif extension == '.csv':
            text, extraction = extract_csv_file(path)
        elif extension == '.pdf':
            text, extraction = extract_pdf(path)
        elif extension == '.docx':
            text, extraction = extract_docx(path)
        elif extension == '.doc':
            text, extraction = extract_doc(path)
        elif extension in ('.jpg', '.jpeg', '.png', '.gif', '.webp', '.heic', '.heif', '.bmp', '.tif', '.tiff'):
            text, extraction = ocr_image(path)
        else:
            raise KnowledgeError('unsupported_file_type')
    text = text.strip()
    if len(text) < 10:
        raise KnowledgeError('empty_text')
    return text[:MAX_TEXT], extraction


def analysis_prompt(text, item, doc, extraction):
    fields = json.dumps(extraction.get('fields') or [], ensure_ascii=False)[:8000]
    return '\n'.join([
        'Ты анализируешь рабочий документ сотрудника фармацевтического производства для базы знаний ERP.',
        'Отвечай только JSON без markdown. Не выдумывай факты, отделы, системы, поля или связи: используй только текст и структуру документа.',
        'Не включай пароли, персональные данные пациентов, зарплаты и секреты. Если они есть, только отметь их наличие в data_quality.',
        'Схема: {"summary":"2-4 предложения по существу", "key_points":["до 7 главных фактов"],',
        '"fields":[{"name":"точное поле", "description":"смысл поля", "example":"пример из документа"}],',
        '"systems":["точные системы/форматы"], "processes":["точные операции"], "handoffs":["источник → получатель: что передаётся"],',
        '"data_quality":["пропуски, неоднозначность, чувствительные данные или проблемы структуры"]}.',
        'fields — только реальные поля/колонки/реквизиты документа, не придуманные для будущей ERP.',
        'Документ: ' + (item.get('name') or 'Документ') + '. Вопрос интервью: ' + (item.get('question') or ''),
        'Должность: ' + (doc.get('position') or '') + '. Отдел: ' + (doc.get('dept') or ''),
        'Поля, найденные при разборе: ' + fields,
        'Содержимое документа:\n' + text[:MAX_MODEL_TEXT],
    ])


def fallback_analysis(text, extraction):
    lines = [re.sub(r'\s+', ' ', line).strip() for line in text.splitlines() if line.strip()]
    return {
        'summary': ' '.join(lines[:3])[:900],
        'key_points': lines[:7],
        'fields': extraction.get('fields') or [],
        'systems': [], 'processes': [], 'handoffs': [],
        'data_quality': ['Резюме сформировано без ИИ: сохранены исходный текст и структура документа.'],
    }


def human_item(value):
    if not isinstance(value, dict):
        return str(value)[:600]
    source = value.get('source') or value.get('from') or value.get('initiator') or ''
    target = value.get('recipient') or value.get('target') or value.get('to') or ''
    detail = value.get('data') or value.get('description') or value.get('text') or ''
    if source or target:
        return (str(source or 'Не указано') + ' → ' + str(target or 'Не указано') +
                (': ' + str(detail) if detail else ''))[:600]
    return json.dumps(value, ensure_ascii=False)[:600]


def normalize_analysis(value, fallback):
    if not isinstance(value, dict):
        raise KnowledgeError('invalid_analysis')
    result = dict(fallback)
    result['summary'] = str(value.get('summary') or fallback['summary'])[:2000]
    for key in ('key_points', 'systems', 'processes', 'handoffs', 'data_quality'):
        items = value.get(key)
        if isinstance(items, list):
            result[key] = [human_item(item) for item in items[:20] if str(item).strip()]
    if isinstance(value.get('fields'), list):
        result['fields'] = [{
            'name': str(field.get('name') or '')[:300],
            'description': str(field.get('description') or '')[:600],
            'example': str(field.get('example') or '')[:300],
        } for field in value['fields'][:100] if isinstance(field, dict) and field.get('name')]
    return result


def update_job(database, attachment_id, status, **values):
    columns = ', '.join(key + '=?' for key in values)
    with connect(database) as con:
        con.execute('UPDATE knowledge_documents SET status=?, ' + columns + ', updated_at=? WHERE attachment_id=?',
                    (status, *values.values(), now_iso(), attachment_id))


def claim_job(database):
    with connect(database) as con:
        row = con.execute("SELECT * FROM knowledge_documents WHERE status='queued' ORDER BY id LIMIT 1").fetchone()
        if not row:
            return None
        changed = con.execute("UPDATE knowledge_documents SET status='processing', updated_at=? WHERE attachment_id=? AND status='queued'",
                              (now_iso(), row['attachment_id'])).rowcount
        return row if changed else None


def process_one(database, summarizer):
    row = claim_job(database)
    if not row:
        return False
    attachment_id = row['attachment_id']
    try:
        with connect(database) as con:
            raw = con.execute('SELECT doc FROM interviews WHERE id=?', (row['interview_id'],)).fetchone()
        if not raw:
            raise KnowledgeError('interview_not_found')
        doc = json.loads(raw['doc'])
        item = next((entry for entry in doc.get('attachments') or [] if entry.get('id') == attachment_id), None)
        if not item:
            raise KnowledgeError('attachment_not_found')
        if item.get('kind') == 'link':
            path = ''
        else:
            if not re.fullmatch(r'[0-9a-f]{16}', row['interview_id']) or not re.fullmatch(r'[0-9a-f]{24}', attachment_id):
                raise KnowledgeError('attachment')
            path = str(Path(database).parent / 'attachments' / row['interview_id'] / attachment_id)
        text, extraction = extract_document(item, path)
        update_job(database, attachment_id, 'analyzing', extracted_text=text, extraction_json=json.dumps(extraction, ensure_ascii=False), error='')
        fallback = fallback_analysis(text, extraction)
        try:
            value = summarizer(analysis_prompt(text, item, doc, extraction))
            analysis = normalize_analysis(value, fallback)
            status, error = 'ready', ''
        except Exception:
            analysis, status, error = fallback, 'extracted', 'ai_unavailable'
        update_job(database, attachment_id, status, analysis_json=json.dumps(analysis, ensure_ascii=False), error=error)
        print('KNOWLEDGE', attachment_id, status, error, flush=True)
    except Exception as error:
        code = str(error) if isinstance(error, KnowledgeError) else 'document_read_failed: ' + str(error)[:300]
        update_job(database, attachment_id, 'failed', error=code)
        print('KNOWLEDGE', attachment_id, 'failed', code, flush=True)
    return True


def knowledge_status(database, interview_id, attachment_ids):
    with connect(database) as con:
        rows = con.execute('SELECT * FROM knowledge_documents WHERE interview_id=? AND attachment_id IN (%s)' % ','.join('?' * len(attachment_ids)),
                           (interview_id, *attachment_ids)).fetchall() if attachment_ids else []
    by_id = {row['attachment_id']: row for row in rows}
    items = []
    for attachment_id in attachment_ids:
        row = by_id.get(attachment_id)
        if not row:
            items.append({'id': attachment_id, 'status': 'queued'})
            continue
        analysis = json.loads(row['analysis_json'] or '{}')
        items.append({'id': attachment_id, 'status': row['status'], 'summary': analysis.get('summary') or '',
                      'error': row['error'] or '', 'name': row['source_name']})
    ready = sum(item['status'] in TERMINAL_STATUSES for item in items)
    failed = sum(item['status'] == 'failed' for item in items)
    extracted = sum(item['status'] == 'extracted' for item in items)
    return {'done': ready == len(items), 'ready': ready, 'total': len(items), 'failed': failed,
            'extracted': extracted, 'items': items}


def list_knowledge(database, query='', limit=100, text_limit=12000):
    limit = max(1, min(200, int(limit)))
    with connect(database) as con:
        if query:
            rows = con.execute('''SELECT * FROM knowledge_documents WHERE source_name LIKE ? OR extracted_text LIKE ? OR analysis_json LIKE ?
                ORDER BY id DESC LIMIT ?''', ('%' + query + '%', '%' + query + '%', '%' + query + '%', limit)).fetchall()
        else:
            rows = con.execute('SELECT * FROM knowledge_documents ORDER BY id DESC LIMIT ?', (limit,)).fetchall()
    items = []
    for row in rows:
        analysis = json.loads(row['analysis_json'] or '{}')
        extraction = json.loads(row['extraction_json'] or '{}')
        items.append({'id': row['id'], 'interviewId': row['interview_id'], 'attachmentId': row['attachment_id'],
                      'status': row['status'], 'sourceName': row['source_name'], 'kind': row['source_kind'],
                      'mime': row['mime'], 'sha256': row['sha256'], 'questionIndex': row['question_index'],
                      'messageIndex': row['message_index'], 'roleKeys': json.loads(row['role_keys'] or '[]'),
                      'department': row['department'], 'position': row['position'], 'personName': row['person_name'],
                      'language': row['language'], 'analysis': analysis, 'extraction': extraction,
                      'error': row['error'], 'text': (row['extracted_text'] or '')[:text_limit],
                      'createdAt': row['created_at'], 'updatedAt': row['updated_at']})
    return items


def knowledge_worker(database, summarizer, stop_event):
    init_knowledge(database)
    with connect(database) as con:
        con.execute("UPDATE knowledge_documents SET status='queued' WHERE status IN ('processing','analyzing')")
    while not stop_event.is_set():
        worked = process_one(database, summarizer)
        if not worked:
            stop_event.wait(1)

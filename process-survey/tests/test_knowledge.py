#!/usr/bin/env python3
"""Проверки извлечения и базы знаний документов."""
import json
import tempfile
import unittest
import urllib.parse
import zipfile
from pathlib import Path

import docx
import openpyxl
from PIL import Image, ImageDraw, ImageFont
from pypdf import PdfReader
from reportlab.pdfgen import canvas

import knowledge
import server
from test_server import SurveyApiTest


def make_xlsx(path):
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = 'Проверка серии'
    sheet.append(['Артикул', 'Количество', 'Ответственный', 'Статус'])
    sheet.append(['BAL-001', 120, 'Иван', 'Готов'])
    sheet.append(['BAL-002', 80, 'Мария', 'Проверка'])
    sheet['E2'] = '=B2*2'
    workbook.save(path)


def make_docx(path):
    document = docx.Document()
    document.add_paragraph('Инструкция по проверке серии Balkan.')
    document.add_paragraph('Мастер проверяет номер серии и подписывает журнал. QA утверждает результат.')
    table = document.add_table(rows=2, cols=2)
    table.rows[0].cells[0].text = 'Этап'
    table.rows[0].cells[1].text = 'Ответственный'
    table.rows[1].cells[0].text = 'Утверждение'
    table.rows[1].cells[1].text = 'QA'
    document.save(path)


def fake_summary(prompt):
    return {
        'summary': 'Тестовое резюме документа о проверке серии',
        'key_points': ['Поля и связи подтверждены'],
        'fields': [{'name': 'Артикул', 'description': 'Код продукта', 'example': 'BAL-001'}],
        'systems': ['Excel'], 'processes': ['Проверка серии'], 'handoffs': ['Склад → QA: серия'],
        'data_quality': [],
    }


class KnowledgeExtractionTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='knowledge-extract-', dir=Path(__file__).parents[1] / 'run')
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_xlsx_docx_pdf_and_csv_keep_business_content(self):
        xlsx = self.root / 'process.xlsx'
        make_xlsx(xlsx)
        text, extraction = knowledge.extract_xlsx(str(xlsx))
        self.assertIn('Артикул', text)
        self.assertIn('BAL-001', text)
        self.assertIn('=B2*2', text)
        self.assertEqual(extraction['fields'][0]['name'], 'Артикул')

        docx_path = self.root / 'instruction.docx'
        make_docx(docx_path)
        text, _ = knowledge.extract_docx(str(docx_path))
        self.assertIn('подписывает журнал', text)
        self.assertIn('QA', text)

        pdf = self.root / 'instruction.pdf'
        page = canvas.Canvas(str(pdf))
        page.drawString(72, 760, 'Balkan batch BAL-001. QA approves the batch record.')
        page.save()
        text, _ = knowledge.extract_pdf(str(pdf))
        self.assertIn('BAL-001', text)
        self.assertIn('QA', text)

        csv_path = self.root / 'process.csv'
        csv_path.write_text('Артикул;Количество\nBAL-003;45\n', encoding='utf-8-sig')
        text, _ = knowledge.extract_csv_file(str(csv_path))
        self.assertIn('BAL-003', text)
        self.assertIn('45', text)

    def test_strict_ooxml_relationships_are_supported(self):
        source = self.root / 'source.docx'
        make_docx(source)
        strict = self.root / 'strict.docx'
        with zipfile.ZipFile(source) as original, zipfile.ZipFile(strict, 'w') as target:
            for info in original.infolist():
                data = original.read(info.filename)
                if info.filename == '_rels/.rels':
                    data = data.replace(b'http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument',
                                        b'http://purl.oclc.org/ooxml/officeDocument/relationships/officeDocument')
                target.writestr(info, data)
        text, extraction = knowledge.extract_docx(str(strict))
        self.assertEqual(extraction['parser'], 'strict-ooxml')
        self.assertIn('подписывает журнал', text)

    def test_structured_handoffs_are_human_readable(self):
        result = knowledge.normalize_analysis({
            'summary': 'Проверка',
            'handoffs': [{'source': 'Иван', 'recipient': 'QA', 'data': 'Серия BAL-001'}],
        }, knowledge.fallback_analysis('Текст документа', {}))
        self.assertEqual(result['handoffs'], ['Иван → QA: Серия BAL-001'])

    def test_image_ocr_and_google_url(self):
        image_path = self.root / 'batch.png'
        image = Image.new('RGB', (1100, 240), 'white')
        draw = ImageDraw.Draw(image)
        try:
            font = ImageFont.truetype('/System/Library/Fonts/Supplemental/Arial.ttf', 54)
        except OSError:
            font = ImageFont.load_default(size=54)
        draw.text((40, 70), 'Balkan Batch 123', fill='black', font=font)
        image.save(image_path)
        text, extraction = knowledge.ocr_image(str(image_path))
        self.assertIn('Balkan', text)
        self.assertIn('123', text)
        self.assertEqual(extraction['parser'], 'macOS Vision')
        url = knowledge.google_csv_url('https://docs.google.com/spreadsheets/d/abc-123/edit#gid=0')
        self.assertEqual(url, 'https://docs.google.com/spreadsheets/d/abc-123/export?format=csv')


class KnowledgeApiTest(SurveyApiTest):
    def test_analysis_becomes_ready_and_available_to_interviewer_admin_and_export(self):
        code, created = self.create()
        self.assertEqual(code, 200)
        token, doc = created['token'], created['doc']
        aid = 'a' * 24
        doc['messages'] = [
            {'role': 'assistant', 'content': 'Приложите шаблон проверки серии', 'phase': 1},
            {'role': 'user', 'content': 'Прикладываю шаблон', 'attachmentIds': [aid]},
        ]
        doc['attachments'] = [{'id': aid, 'kind': 'file', 'name': 'process.xlsx',
                               'mime': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                               'size': 1, 'sha256': 'test', 'questionIndex': 0, 'messageIndex': 1,
                               'question': 'Приложите шаблон проверки серии', 'createdAt': doc['createdAt']}]
        server.save_doc(doc['id'], doc)
        attachment = Path(server.DB_PATH).parent / 'attachments' / doc['id'] / aid
        attachment.parent.mkdir(parents=True)
        make_xlsx(attachment)
        server.enqueue_knowledge(server.DB_PATH, doc, doc['attachments'][0])

        code, pending = self.request('POST', '/api/me/attachments/analyze', {'ids': [aid]}, token=token)
        self.assertEqual(code, 202)
        self.assertFalse(pending['done'])
        self.assertTrue(knowledge.process_one(server.DB_PATH, fake_summary))
        code, ready = self.request('POST', '/api/me/attachments/analyze', {'ids': [aid]}, token=token)
        self.assertEqual(code, 200)
        self.assertTrue(ready['done'])
        self.assertEqual(ready['items'][0]['status'], 'ready')
        self.assertIn('проверке серии', ready['items'][0]['summary'])

        code, admin = self.request('GET', '/api/admin/knowledge?q=' + urllib.parse.quote('Артикул'), admin='test-admin-key')
        self.assertEqual(code, 200)
        self.assertEqual(admin['total'], 1)
        self.assertEqual(admin['items'][0]['sourceName'], 'process.xlsx')
        self.assertEqual(admin['items'][0]['analysis']['fields'][0]['name'], 'Артикул')
        self.assertIn('BAL-001', admin['items'][0]['text'])
        turns = server.turn_messages(doc)
        self.assertIn('Тестовое резюме документа', turns[-1]['content'])

        from export_erp2 import export_database
        output = Path(self.temp.name) / 'export.json'
        result = export_database(server.DB_PATH, output)
        payload = json.loads(output.read_text(encoding='utf-8'))
        self.assertEqual(result['knowledge_count'], 1)
        self.assertEqual(payload['knowledge_documents'][0]['analysis']['systems'], ['Excel'])


if __name__ == '__main__':
    unittest.main(verbosity=2)

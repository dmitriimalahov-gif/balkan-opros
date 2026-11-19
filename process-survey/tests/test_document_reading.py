#!/usr/bin/env python3
"""Фото и сканы документов на сервере без macOS Vision и «что это за документ» в базе знаний."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image
from reportlab.pdfgen import canvas

import knowledge
import server
from test_server import SurveyApiTest
from tests.test_knowledge import make_xlsx
from tests.test_remote_analysis import FakeResponse

PHOTO_TEXT = 'ЖУРНАЛ ПРИЁМКИ СЫРЬЯ\n19.11 | Лактоза | L-2231 | 150'
NO_MACOS_VISION = '/nonexistent/xcrun'


def typed_summary(prompt):
    return {
        'summary': 'Журнал учёта приёмки сырья по сериям',
        'document_type': 'Журнал приёмки сырья',
        'purpose': 'Кладовщик записывает каждую поставку сырья',
        'key_points': [], 'fields': [], 'systems': [], 'processes': ['Приёмка сырья'],
        'handoffs': [], 'data_quality': [],
    }


class ImageReadingTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='document-reading-')
        self.root = Path(self.temp.name)
        self.photo = self.root / 'attachment-without-extension'
        Image.new('RGB', (40, 20), 'white').save(self.photo, format='JPEG')

    def tearDown(self):
        self.temp.cleanup()

    def test_photo_is_read_by_vision_model_when_macos_vision_is_missing(self):
        calls = []

        def reader(path):
            calls.append(path)
            return PHOTO_TEXT

        with patch.object(knowledge, 'MACOS_VISION', NO_MACOS_VISION):
            text, extraction = knowledge.extract_document({'name': 'IMG_7530.jpeg'}, str(self.photo), image_reader=reader)
        self.assertEqual(text, PHOTO_TEXT)
        self.assertEqual(extraction['parser'], 'vision-model')
        self.assertEqual(calls, [str(self.photo)])

    def test_photo_without_any_reader_fails_with_clear_code(self):
        with patch.object(knowledge, 'MACOS_VISION', NO_MACOS_VISION):
            with self.assertRaisesRegex(knowledge.KnowledgeError, 'ocr_unavailable'):
                knowledge.extract_document({'name': 'IMG_7530.jpeg'}, str(self.photo))

    def test_scanned_pdf_pages_go_to_the_same_reader(self):
        scan = self.root / 'scan.pdf'
        page = canvas.Canvas(str(scan))
        page.showPage()
        page.save()

        def reader(path):
            return PHOTO_TEXT

        with patch.object(knowledge, 'ocr_pdf', return_value=(PHOTO_TEXT, 'vision-model')) as ocr:
            text, extraction = knowledge.extract_pdf(str(scan), image_reader=reader)
        ocr.assert_called_once_with(str(scan), reader)
        self.assertEqual(text, PHOTO_TEXT)
        self.assertEqual(extraction['parser'], 'vision-model')

    def test_server_sends_photo_to_gateway_as_image(self):
        payload = {'choices': [{'message': {'content': PHOTO_TEXT}}]}
        with patch.object(server, 'ANALYSIS_BASE', 'https://litellm.test'), \
             patch.object(server, 'ANALYSIS_KEY', 'test-key'), \
             patch.object(server, 'VISION_MODEL', 'auto'), \
             patch.object(server.urllib.request, 'urlopen', return_value=FakeResponse(payload)) as call:
            text = server.remote_image_text(str(self.photo))
        self.assertEqual(text, PHOTO_TEXT)
        body = json.loads(call.call_args.args[0].data)
        self.assertEqual(body['model'], 'auto')
        self.assertNotIn('temperature', body)
        images = [part for part in body['messages'][0]['content'] if part.get('type') == 'image_url']
        self.assertEqual(len(images), 1)
        self.assertTrue(images[0]['image_url']['url'].startswith('data:image/jpeg;base64,'))

    def test_server_rejects_formats_the_gateway_cannot_read(self):
        tiff = self.root / 'scan-tiff'
        tiff.write_bytes(b'II*\x00' + b'\x00' * 32)
        with self.assertRaisesRegex(server.LLMError, 'image_format_unsupported'):
            server.remote_image_text(str(tiff))

    def test_image_reader_is_enabled_only_with_gateway(self):
        with patch.object(server, 'ANALYSIS_BASE', 'https://litellm.test'), patch.object(server, 'ANALYSIS_KEY', 'k'):
            self.assertIs(server.knowledge_image_reader(), server.remote_image_text)
        with patch.object(server, 'ANALYSIS_BASE', ''), patch.object(server, 'ANALYSIS_KEY', ''):
            self.assertIsNone(server.knowledge_image_reader())


class DocumentTypeTest(unittest.TestCase):
    def test_analysis_keeps_what_the_document_is(self):
        result = knowledge.normalize_analysis(typed_summary(''), knowledge.fallback_analysis('Текст документа', {}))
        self.assertEqual(result['document_type'], 'Журнал приёмки сырья')
        self.assertEqual(result['purpose'], 'Кладовщик записывает каждую поставку сырья')

    def test_prompt_asks_what_the_document_is(self):
        prompt = knowledge.analysis_prompt('текст документа', {'name': 'IMG_7530.jpeg'}, {}, {})
        self.assertIn('"document_type"', prompt)
        self.assertIn('"purpose"', prompt)

    def test_fallback_without_ai_has_empty_type(self):
        fallback = knowledge.fallback_analysis('Текст документа', {})
        self.assertEqual(fallback['document_type'], '')
        self.assertEqual(fallback['purpose'], '')


class DocumentTypeApiTest(SurveyApiTest):
    def test_interviewer_and_status_see_what_the_document_is(self):
        code, created = self.create()
        self.assertEqual(code, 200)
        token, doc = created['token'], created['doc']
        aid = 'b' * 24
        doc['messages'] = [
            {'role': 'assistant', 'content': 'Приложите журнал приёмки', 'phase': 1},
            {'role': 'user', 'content': 'Прикладываю журнал', 'attachmentIds': [aid]},
        ]
        doc['attachments'] = [{'id': aid, 'kind': 'file', 'name': 'journal.xlsx',
                               'mime': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                               'size': 1, 'sha256': 'test', 'questionIndex': 0, 'messageIndex': 1,
                               'question': 'Приложите журнал приёмки', 'createdAt': doc['createdAt']}]
        server.save_doc(doc['id'], doc)
        attachment = Path(server.DB_PATH).parent / 'attachments' / doc['id'] / aid
        attachment.parent.mkdir(parents=True)
        make_xlsx(attachment)
        server.enqueue_knowledge(server.DB_PATH, doc, doc['attachments'][0])
        self.assertTrue(knowledge.process_one(server.DB_PATH, typed_summary))

        code, ready = self.request('POST', '/api/me/attachments/analyze', {'ids': [aid]}, token=token)
        self.assertEqual(code, 200)
        self.assertEqual(ready['items'][0]['documentType'], 'Журнал приёмки сырья')
        turns = server.turn_messages(doc)
        self.assertIn('Журнал приёмки сырья', turns[-1]['content'])


if __name__ == '__main__':
    unittest.main(verbosity=2)

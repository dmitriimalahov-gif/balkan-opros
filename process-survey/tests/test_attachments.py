#!/usr/bin/env python3
"""Проверки загрузки, привязки и выгрузки материалов к вопросам."""
import json
import unittest
import urllib.error
import urllib.request
from pathlib import Path

import server
from test_server import SurveyApiTest
from export_erp2 import export_database


class AttachmentApiTest(SurveyApiTest):
    def raw_request(self, method, path, data=None, token=None, admin=None, content_type=None):
        headers = {}
        if token:
            headers['Authorization'] = 'Bearer ' + token
        if admin:
            headers['X-Admin-Key'] = admin
        if content_type:
            headers['Content-Type'] = content_type
        req = urllib.request.Request(self.base + path, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=10) as response:
                raw = response.read()
                if response.headers.get_content_type() == 'application/json':
                    return response.status, json.loads(raw), response.headers
                return response.status, raw, response.headers
        except urllib.error.HTTPError as error:
            raw = error.read()
            try:
                payload = json.loads(raw)
            except Exception:
                payload = raw
            return error.code, payload, error.headers

    def create_with_question(self):
        code, created = self.create()
        self.assertEqual(code, 200)
        token = created['token']
        doc = created['doc']
        doc['messages'] = [{'role': 'assistant', 'content': 'Какие файлы используете?', 'phase': 2}]
        code, _ = self.request('PUT', '/api/me', {'doc': doc}, token=token)
        self.assertEqual(code, 200)
        return token, doc

    def upload(self, token, name='отчёт.xlsx', content=b'excel-test', question=0):
        path = '/api/me/attachments?question=%d&name=%s' % (question, urllib.parse.quote(name))
        return self.raw_request('POST', path, content, token=token,
                                content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')

    def test_file_link_answer_download_export_and_delete(self):
        token, doc = self.create_with_question()
        code, uploaded, _ = self.upload(token)
        self.assertEqual(code, 200, uploaded)
        attachment = uploaded['attachment']
        self.assertEqual(attachment['name'], 'отчёт.xlsx')
        self.assertEqual(attachment['kind'], 'file')
        self.assertEqual(attachment['questionIndex'], 0)
        self.assertEqual(attachment['size'], 10)
        self.assertNotIn('path', attachment)

        code, linked, _ = self.raw_request('POST', '/api/me/attachment-links', json.dumps({
            'question': 0, 'url': 'https://docs.google.com/spreadsheets/d/example/edit#gid=0',
        }).encode(), token=token, content_type='application/json')
        self.assertEqual(code, 200, linked)
        self.assertEqual(linked['attachment']['kind'], 'link')

        doc['messages'].append({
            'role': 'user', 'content': 'Приложил шаблон', 'attachmentIds': [attachment['id'], linked['attachment']['id']],
        })
        code, _ = self.request('PUT', '/api/me', {'doc': doc}, token=token)
        self.assertEqual(code, 200)
        code, loaded = self.request('GET', '/api/me', token=token)
        self.assertEqual(code, 200)
        loaded_doc = loaded['doc']
        self.assertEqual(len(loaded_doc['attachments']), 2)
        self.assertEqual(loaded_doc['attachments'][0]['messageIndex'], 1)
        self.assertEqual(loaded_doc['messages'][1]['attachmentIds'], [attachment['id'], linked['attachment']['id']])

        code, raw, headers = self.raw_request('GET', '/api/me/attachments/' + attachment['id'], token=token)
        self.assertEqual((code, raw), (200, b'excel-test'))
        self.assertIn('attachment', headers.get('Content-Disposition', ''))
        code, raw, _ = self.raw_request('GET', '/api/admin/attachments/' + attachment['id'], admin='test-admin-key')
        self.assertEqual((code, raw), (200, b'excel-test'))
        code, _, _ = self.raw_request('GET', '/api/me/attachments/' + attachment['id'])
        self.assertEqual(code, 404)

        output = Path(self.temp.name) / 'erp.json'
        export_database(server.DB_PATH, output)
        exported = json.loads(output.read_text(encoding='utf-8'))['interviews'][0]
        self.assertEqual(len(exported['attachments']), 2)
        self.assertEqual(exported['attachments'][0]['sha256'], attachment['sha256'])
        self.assertNotIn('token_hash', output.read_text(encoding='utf-8'))

        code, _ = self.request('DELETE', '/api/admin/interviews/' + doc['id'], admin='test-admin-key')
        self.assertEqual(code, 200)
        self.assertFalse((Path(server.DB_PATH).parent / 'attachments' / doc['id']).exists())

    def test_remove_pending_and_reject_invalid_materials(self):
        token, doc = self.create_with_question()
        code, uploaded, _ = self.upload(token)
        attachment = uploaded['attachment']
        code, deleted, _ = self.raw_request('DELETE', '/api/me/attachments/' + attachment['id'], token=token)
        self.assertEqual(code, 200, deleted)
        code, loaded = self.request('GET', '/api/me', token=token)
        self.assertEqual(loaded['doc']['attachments'], [])

        code, error, _ = self.upload(token, name='опасно.exe')
        self.assertEqual((code, error), (400, {'error': 'unsupported_file_type'}))
        for url in ('https://example.com/table', 'http://docs.google.com/spreadsheets/d/example'):
            code, error, _ = self.raw_request('POST', '/api/me/attachment-links', json.dumps({
                'question': 0, 'url': url,
            }).encode(), token=token, content_type='application/json')
            self.assertEqual((code, error), (400, {'error': 'invalid_google_sheet_url'}))

        code, error, _ = self.upload(token, name='пустой.pdf', content=b'')
        self.assertEqual((code, error), (400, {'error': 'empty_file'}))

    def test_chunk_upload_integrity_and_invalid_offset(self):
        token, _ = self.create_with_question()
        upload_id = 'a' * 32
        content = b'first-second'
        params = 'upload=%s&question=0&name=parts.pdf&size=%d' % (upload_id, len(content))
        code, response, _ = self.raw_request(
            'POST', '/api/me/attachments/chunk?' + params + '&offset=0', content[:6],
            token=token, content_type='application/octet-stream')
        self.assertEqual((code, response['received']), (200, 6))
        code, response, _ = self.raw_request(
            'POST', '/api/me/attachments/chunk?' + params + '&offset=6', content[6:],
            token=token, content_type='application/octet-stream')
        self.assertEqual((code, response['received']), (200, len(content)))
        code, completed, _ = self.raw_request('POST', '/api/me/attachments/complete', json.dumps({
            'upload': upload_id, 'question': 0, 'name': 'parts.pdf', 'size': len(content),
        }).encode(), token=token, content_type='application/json')
        self.assertEqual(code, 200, completed)
        attachment = completed['attachment']
        self.assertEqual(attachment['sha256'], __import__('hashlib').sha256(content).hexdigest())
        code, raw, _ = self.raw_request('GET', '/api/me/attachments/' + attachment['id'], token=token)
        self.assertEqual((code, raw), (200, content))

        bad_params = 'upload=%s&question=0&name=bad.pdf&size=6&offset=4' % ('b' * 32)
        code, error, _ = self.raw_request(
            'POST', '/api/me/attachments/chunk?' + bad_params, b'xx',
            token=token, content_type='application/octet-stream')
        self.assertEqual((code, error), (400, {'error': 'offset'}))

    def test_file_size_and_question_limits(self):
        token, _ = self.create_with_question()
        params = 'upload=%s&question=0&name=huge.pdf&size=%d&offset=0' % ('c' * 32, server.MAX_FILE + 1)
        code, error, _ = self.raw_request(
            'POST', '/api/me/attachments/chunk?' + params, b'x',
            token=token, content_type='application/octet-stream')
        self.assertEqual((code, error), (400, {'error': 'file_too_large'}))

        for index in range(server.MAX_FILES_PER_QUESTION):
            code, uploaded, _ = self.upload(token, name='file-%d.pdf' % index, content=b'x')
            self.assertEqual(code, 200, uploaded)
        code, error, _ = self.upload(token, name='sixth.pdf', content=b'x')
        self.assertEqual((code, error), (400, {'error': 'too_many_attachments'}))


if __name__ == '__main__':
    unittest.main(verbosity=2)

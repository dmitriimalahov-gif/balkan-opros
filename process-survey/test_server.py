#!/usr/bin/env python3
"""Интеграционные проверки API опроса на временной базе данных."""
import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import server


class SurveyApiTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='api-test-', dir=Path(__file__).parent / 'run')
        root = Path(self.temp.name)
        server.DB_PATH = str(root / 'survey.db')
        server.ADMIN_FILE = str(root / 'admin.txt')
        server.TUNNEL_LOG = str(root / 'tunnel.log')
        server.PUSHED_FILE = str(root / 'pushed-url')
        Path(server.ADMIN_FILE).write_text('test-admin-key\n', encoding='utf-8')
        Path(server.TUNNEL_LOG).write_text('https://test.example.com\n', encoding='utf-8')
        Path(server.PUSHED_FILE).write_text(server.STABLE_URL + '\n', encoding='utf-8')
        self._original_ai_available = server.ai_available
        self._original_voice_available = server.voice_available
        self._original_warm_async = server.warm_async
        server.ai_available = lambda: False
        server.voice_available = lambda: False
        server.warm_async = lambda: None
        server._hits = {}
        server.init_db()
        self.httpd = ThreadingHTTPServer(('127.0.0.1', 0), server.Handler)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        self.base = 'http://127.0.0.1:%d' % self.httpd.server_port

    def tearDown(self):
        server.ai_available = self._original_ai_available
        server.voice_available = self._original_voice_available
        server.warm_async = self._original_warm_async
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=5)
        self.temp.cleanup()

    def request(self, method, path, body=None, token=None, admin=None):
        headers = {}
        data = None
        if body is not None:
            data = json.dumps(body, ensure_ascii=False).encode('utf-8')
            headers['Content-Type'] = 'application/json'
        if token:
            headers['Authorization'] = 'Bearer ' + token
        if admin:
            headers['X-Admin-Key'] = admin
        req = urllib.request.Request(self.base + path, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=10) as response:
                return response.status, json.load(response)
        except urllib.error.HTTPError as error:
            return error.code, json.load(error)

    def create(self):
        return self.request('POST', '/api/interviews', {
            'name': 'Тестовый сотрудник',
            'dept': 'it',
            'position': 'Тестовая должность',
            'lang': 'ru',
            'consent': True,
        })

    def test_health_config_and_validation(self):
        code, health = self.request('GET', '/healthz')
        self.assertEqual((code, health), (200, {'ok': True}))
        code, config = self.request('GET', '/api/config')
        self.assertEqual(code, 200)
        self.assertFalse(config['ai'])
        self.assertEqual(config['stableUrl'], server.STABLE_URL)
        code, error = self.request('POST', '/api/interviews', {})
        self.assertEqual((code, error), (400, {'error': 'fields'}))
        code, error = self.request('GET', '/api/admin/interviews')
        self.assertEqual((code, error), (401, {'error': 'unauthorized'}))

    def test_interview_resume_admin_and_delete_flow(self):
        code, created = self.create()
        self.assertEqual(code, 200)
        token = created['token']
        doc = created['doc']
        self.assertEqual(doc['mode'], 'script')
        self.assertEqual(doc['status'], 'in_progress')

        code, loaded = self.request('GET', '/api/me', token=token)
        self.assertEqual(code, 200)
        self.assertEqual(loaded['doc']['id'], doc['id'])

        doc['messages'] = [
            {'role': 'assistant', 'content': 'Первый вопрос?', 'phase': 1,
             'options': ['Ежедневно', 'Еженедельно'], 'mode': 'many'},
            {'role': 'user', 'content': 'Ежедневно — тестовый ответ',
             'picked': ['Ежедневно'], 'own': 'тестовый ответ'},
        ]
        code, saved = self.request('PUT', '/api/me', {'doc': doc}, token=token)
        self.assertEqual((code, saved['ok']), (200, True))
        code, loaded = self.request('GET', '/api/me', token=token)
        self.assertEqual(len(loaded['doc']['messages']), 2)
        self.assertEqual(loaded['doc']['messages'][1]['picked'], ['Ежедневно'])

        code, error = self.request('POST', '/api/me/turn', {}, token=token)
        self.assertEqual((code, error), (503, {'error': 'ai_unavailable'}))

        code, admin = self.request('GET', '/api/admin/interviews', admin='test-admin-key')
        self.assertEqual(code, 200)
        self.assertEqual(len(admin['interviews']), 1)
        self.assertEqual(admin['interviews'][0]['id'], doc['id'])

        code, resumed = self.request('POST', '/api/admin/interviews/%s/resume-link' % doc['id'],
                                     {}, admin='test-admin-key')
        self.assertEqual(code, 200)
        self.assertTrue(resumed['url'].startswith(server.STABLE_URL + '#t='))
        new_token = resumed['url'].split('#t=', 1)[1]
        code, _ = self.request('GET', '/api/me', token=token)
        self.assertEqual(code, 404)
        code, loaded = self.request('GET', '/api/me', token=new_token)
        self.assertEqual(code, 200)
        self.assertEqual(len(loaded['doc']['messages']), 2)

        summary = {'role_summary': 'Проверка', 'processes': []}
        code, updated = self.request('PUT', '/api/admin/interviews/%s/summary' % doc['id'],
                                     {'summary': summary}, admin='test-admin-key')
        self.assertEqual(code, 200)
        self.assertEqual(updated['doc']['summaryBy'], 'owner')

        code, deleted = self.request('DELETE', '/api/admin/interviews/%s' % doc['id'],
                                     admin='test-admin-key')
        self.assertEqual((code, deleted), (200, {'ok': True}))
        code, _ = self.request('GET', '/api/me', token=new_token)
        self.assertEqual(code, 404)


if __name__ == '__main__':
    unittest.main(verbosity=2)

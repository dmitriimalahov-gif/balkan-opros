#!/usr/bin/env python3
"""Проверки авторизации, очереди и кэша голоса владельца."""
import json
import tempfile
import urllib.request
from pathlib import Path

import owner_voice
import server
from test_server import SurveyApiTest


class OwnerVoiceApiTest(SurveyApiTest):
    def setUp(self):
        super().setUp()
        self.old_voice_dir = owner_voice.VOICE_DIR
        self.old_run_dir = owner_voice.RUN_DIR
        self.voice_temp = tempfile.TemporaryDirectory(prefix='owner-voice-test-', dir=Path(__file__).parents[1] / 'run')
        root = Path(self.voice_temp.name)
        owner_voice.VOICE_DIR = root / 'voice'
        owner_voice.RUN_DIR = root / 'run'
        server.voice_available = lambda: True

    def tearDown(self):
        owner_voice.VOICE_DIR = self.old_voice_dir
        owner_voice.RUN_DIR = self.old_run_dir
        server.voice_available = lambda: False
        self.voice_temp.cleanup()
        super().tearDown()

    def create_with_question(self, text='Первый вопрос голосом руководителя?', lang='ru'):
        code, created = self.create()
        self.assertEqual(code, 200)
        doc = created['doc']
        doc['lang'] = lang
        doc['messages'] = [
            {'role': 'assistant', 'content': text, 'phase': 1},
            {'role': 'user', 'content': 'Тестовый ответ'},
        ]
        code, _ = self.request('PUT', '/api/me', {'doc': doc}, token=created['token'])
        self.assertEqual(code, 200)
        return created['token'], doc

    def audio(self, path, token):
        request = urllib.request.Request(self.base + path, headers={'Authorization': 'Bearer ' + token})
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status, response.headers, response.read()

    def test_only_saved_assistant_question_is_queued_and_audio_is_cached(self):
        token, _ = self.create_with_question()
        code, config = self.request('GET', '/api/config')
        self.assertEqual(code, 200)
        self.assertTrue(config['ownerVoice'])
        code, error = self.request('GET', '/api/me/voice/1', token=token)
        self.assertEqual((code, error), (404, {'error': 'not_found'}))
        code, pending = self.request('GET', '/api/me/voice/0', token=token)
        self.assertEqual((code, pending), (202, {'status': 'working', 'retryAfter': 2}))
        jobs = list((owner_voice.VOICE_DIR / 'jobs').glob('*.json'))
        self.assertEqual(len(jobs), 1)
        job = json.loads(jobs[0].read_text(encoding='utf-8'))
        self.assertEqual(job['text'], 'Первый вопрос голосом руководителя?')
        self.assertEqual(job['lang'], 'ru')
        self.assertEqual(job['voice'], 'dmitrii')
        self.assertEqual(job['profile'], 'numerom-dmitrii-v2-clean')
        code, _ = self.request('GET', '/api/me/voice/0', token=token)
        self.assertEqual(code, 202)
        self.assertEqual(len(list((owner_voice.VOICE_DIR / 'jobs').glob('*.json'))), 1)
        code, _ = self.request('GET', '/api/me/voice/0')
        self.assertEqual(code, 404)

        audio = b'fake-audio-for-api-contract'
        cache = owner_voice.VOICE_DIR / 'clips' / job['hash']
        cache.mkdir(parents=True)
        (cache / 'audio.m4a').write_bytes(audio)
        (cache / 'ready.json').write_text('{"hash": "%s"}\n' % job['hash'], encoding='utf-8')
        jobs[0].unlink()
        code, headers, body = self.audio('/api/me/voice/0', token)
        self.assertEqual(code, 200)
        self.assertEqual(headers.get_content_type(), 'audio/mp4')
        self.assertIn("media-src 'self' blob:", headers.get('Content-Security-Policy'))
        self.assertEqual(body, audio)
        self.assertFalse(jobs[0].exists())

    def test_public_welcome_voice_is_fixed_cached_text(self):
        code, pending = self.request('GET', '/api/welcome-voice?lang=ru')
        self.assertEqual(code, 202)
        self.assertEqual(pending['status'], 'working')
        job_path = next((owner_voice.VOICE_DIR / 'jobs').glob('*.json'))
        job = json.loads(job_path.read_text(encoding='utf-8'))
        self.assertEqual(job['text'], server.WELCOME_VOICE['ru'])
        self.assertEqual(job['lang'], 'ru')
        code, error = self.request('GET', '/api/welcome-voice?lang=en')
        self.assertEqual((code, error), (400, {'error': 'lang'}))
        audio = b'welcome-audio'
        cache = owner_voice.VOICE_DIR / 'clips' / job['hash']
        cache.mkdir(parents=True)
        (cache / 'audio.m4a').write_bytes(audio)
        (cache / 'ready.json').write_text('{}\n', encoding='utf-8')
        with urllib.request.urlopen(self.base + '/api/welcome-voice?lang=ru', timeout=10) as response:
            self.assertEqual(response.status, 200)
            self.assertEqual(response.headers.get_content_type(), 'audio/mp4')
            self.assertEqual(response.read(), audio)

    def test_prefetch_queues_current_and_next_two_role_questions_without_duplicates(self):
        from role_packs import role_questions
        token, doc = self.create_with_question()
        doc['messages'] = doc['messages'][:1]
        self.assertEqual(self.request('PUT', '/api/me', {'doc': doc}, token=token)[0], 200)
        code, pending = self.request('POST', '/api/me/voice-prefetch', {'message': 0, 'count': 2}, token=token)
        self.assertEqual(code, 202)
        self.assertEqual(pending['queued'], 3)
        self.assertEqual(pending['failed'], 0)
        jobs = [json.loads(path.read_text(encoding='utf-8')) for path in (owner_voice.VOICE_DIR / 'jobs').glob('*.json')]
        self.assertEqual(len(jobs), 3)
        texts = {job['text'] for job in jobs}
        self.assertIn('Первый вопрос голосом руководителя?', texts)
        for question in role_questions(doc, 'ru')[1:3]:
            self.assertIn(question['text'], texts)
        code, _ = self.request('POST', '/api/me/voice-prefetch', {'message': 0, 'count': 2}, token=token)
        self.assertEqual(code, 202)
        self.assertEqual(len(list((owner_voice.VOICE_DIR / 'jobs').glob('*.json'))), 3)
        code, error = self.request('POST', '/api/me/voice-prefetch', {'message': 1, 'count': 2}, token=token)
        self.assertEqual((code, error), (404, {'error': 'not_found'}))

    def test_romanian_job_and_failure_have_no_browser_voice_substitute(self):
        token, _ = self.create_with_question('Cum arată procesul dumneavoastră de lucru?', 'ro')
        code, pending = self.request('GET', '/api/me/voice/0', token=token)
        self.assertEqual(code, 202)
        self.assertEqual(pending['status'], 'working')
        job_path = next((owner_voice.VOICE_DIR / 'jobs').glob('*.json'))
        job = json.loads(job_path.read_text(encoding='utf-8'))
        self.assertEqual(job['lang'], 'ro')
        cache = owner_voice.VOICE_DIR / 'clips' / job['hash']
        cache.mkdir(parents=True)
        (cache / 'failed.json').write_text('{"error": "test"}\n', encoding='utf-8')
        code, error = self.request('GET', '/api/me/voice/0', token=token)
        self.assertEqual((code, error), (503, {'error': 'owner_voice_failed'}))
        server.voice_available = lambda: False
        code, error = self.request('GET', '/api/me/voice/0', token=token)
        self.assertEqual((code, error), (503, {'error': 'owner_voice_unavailable'}))


if __name__ == '__main__':
    import unittest
    unittest.main(verbosity=2)

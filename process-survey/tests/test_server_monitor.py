#!/usr/bin/env python3
"""Сторож постоянного сервера: одно уведомление при сбое опроса или ИИ-модели и одно при восстановлении."""
import http.server
import os
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / 'monitor-server.sh'
HEALTHY = (200, b'{"ok": true}')
AUTH_REQUIRED = (401, b'')
BAD_GATEWAY = (502, b'')
ONLINE = (200, b'Success')


class _Handler(http.server.BaseHTTPRequestHandler):
    routes = {}

    def do_GET(self):
        status, body = self.routes.get(self.path, (404, b''))
        self.send_response(status)
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


class ServerMonitorTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.httpd = http.server.ThreadingHTTPServer(('127.0.0.1', 0), _Handler)
        cls.base = 'http://127.0.0.1:%d' % cls.httpd.server_address[1]
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def setUp(self):
        self.state = tempfile.TemporaryDirectory()
        self.set_routes(survey=HEALTHY, llm=AUTH_REQUIRED, online=ONLINE)

    def tearDown(self):
        self.state.cleanup()

    def set_routes(self, survey, llm, online):
        _Handler.routes = {'/healthz': survey, '/models': llm, '/online': online}

    def run_monitor(self):
        # Прокси из окружения (VPN, корпоративная сеть) не должен перехватывать запросы к 127.0.0.1.
        env = {k: v for k, v in os.environ.items() if k.lower() not in ('http_proxy', 'https_proxy', 'all_proxy')}
        env.update(
            NO_PROXY='127.0.0.1,localhost',
            no_proxy='127.0.0.1,localhost',
            SURVEY_HEALTH_URL=self.base + '/healthz',
            SURVEY_LLM_URL=self.base + '/models',
            SURVEY_ONLINE_URL=self.base + '/online',
            SURVEY_MONITOR_STATE=self.state.name,
            SURVEY_MONITOR_FAILS='2',
            SURVEY_MONITOR_TIMEOUT='5',
            SURVEY_NOTIFY='0',
        )
        result = subprocess.run(['/bin/bash', str(SCRIPT)], env=env, capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return [line for line in result.stdout.splitlines() if line.startswith('УВЕДОМЛЕНИЕ')]

    def test_healthy_server_sends_no_notification(self):
        self.assertEqual(self.run_monitor(), [])
        self.assertEqual(self.run_monitor(), [])

    def test_survey_failure_notifies_once_after_consecutive_failures(self):
        self.set_routes(survey=BAD_GATEWAY, llm=AUTH_REQUIRED, online=ONLINE)
        self.assertEqual(self.run_monitor(), [], 'один сбой — ещё не тревога')
        alerts = self.run_monitor()
        self.assertEqual(len(alerts), 1)
        self.assertIn('Опрос', alerts[0])
        self.assertIn('не отвечает', alerts[0])
        self.assertEqual(self.run_monitor(), [], 'та же поломка не повторяет уведомление')

    def test_survey_without_ok_flag_counts_as_failure(self):
        self.set_routes(survey=(200, b'{"ok": false}'), llm=AUTH_REQUIRED, online=ONLINE)
        self.run_monitor()
        self.assertEqual(len(self.run_monitor()), 1)

    def test_recovery_after_alert_notifies_once(self):
        self.set_routes(survey=BAD_GATEWAY, llm=AUTH_REQUIRED, online=ONLINE)
        self.run_monitor()
        self.run_monitor()
        self.set_routes(survey=HEALTHY, llm=AUTH_REQUIRED, online=ONLINE)
        alerts = self.run_monitor()
        self.assertEqual(len(alerts), 1)
        self.assertIn('снова работает', alerts[0])
        self.assertEqual(self.run_monitor(), [])

    def test_short_blip_without_alert_stays_silent(self):
        self.set_routes(survey=BAD_GATEWAY, llm=AUTH_REQUIRED, online=ONLINE)
        self.run_monitor()
        self.set_routes(survey=HEALTHY, llm=AUTH_REQUIRED, online=ONLINE)
        self.assertEqual(self.run_monitor(), [])
        self.set_routes(survey=BAD_GATEWAY, llm=AUTH_REQUIRED, online=ONLINE)
        self.assertEqual(self.run_monitor(), [], 'счётчик сбоев сбрасывается после успешной проверки')

    def test_ai_gateway_error_notifies_about_model(self):
        self.set_routes(survey=HEALTHY, llm=BAD_GATEWAY, online=ONLINE)
        self.run_monitor()
        alerts = self.run_monitor()
        self.assertEqual(len(alerts), 1)
        self.assertIn('ИИ', alerts[0])

    def test_corrupted_counter_file_does_not_silence_alert(self):
        Path(self.state.name, 'monitor-survey.fails').write_text('abc')
        self.set_routes(survey=BAD_GATEWAY, llm=AUTH_REQUIRED, online=ONLINE)
        self.run_monitor()
        self.assertEqual(len(self.run_monitor()), 1)

    def test_offline_mac_raises_no_false_alarm(self):
        self.set_routes(survey=BAD_GATEWAY, llm=BAD_GATEWAY, online=(503, b''))
        for _ in range(3):
            self.assertEqual(self.run_monitor(), [])


if __name__ == '__main__':
    unittest.main()

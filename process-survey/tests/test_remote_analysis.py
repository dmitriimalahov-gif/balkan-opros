#!/usr/bin/env python3
"""Контракт внешней модели анализа и резервной локальной генерации."""
import json
import unittest
from unittest.mock import patch

import server


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self, *args):
        return json.dumps(self.payload, ensure_ascii=False).encode('utf-8')


class RemoteAnalysisTest(unittest.TestCase):
    def test_openai_compatible_json_request(self):
        payload = {'choices': [{'message': {'content': '{"summary":"Готово","fields":[]}'}}]}
        with patch.object(server, 'ANALYSIS_BASE', 'https://llm.test'), \
             patch.object(server, 'ANALYSIS_KEY', 'test-key'), \
             patch.object(server, 'ANALYSIS_MODEL', 'test-model'), \
             patch.object(server.urllib.request, 'urlopen', return_value=FakeResponse(payload)) as call:
            result = server.document_summary('Разбери тестовый документ')
        self.assertEqual(result['summary'], 'Готово')
        request = call.call_args.args[0]
        self.assertEqual(request.full_url, 'https://llm.test/v1/chat/completions')
        self.assertEqual(request.headers['Authorization'], 'Bearer test-key')
        body = json.loads(request.data)
        self.assertEqual(body['model'], 'test-model')
        self.assertEqual(body['response_format'], {'type': 'json_object'})
        self.assertGreaterEqual(body['max_tokens'], 1500)

    def test_remote_failure_falls_back_to_ollama(self):
        with patch.object(server, 'ANALYSIS_BASE', 'https://llm.test'), \
             patch.object(server, 'ANALYSIS_KEY', 'test-key'), \
             patch.object(server, 'remote_analysis_chat', side_effect=server.LLMError('down')), \
             patch.object(server, 'ollama_chat', return_value='{"summary":"Локальный резерв"}') as local:
            result = server.document_summary('Тест')
        self.assertEqual(result['summary'], 'Локальный резерв')
        local.assert_called_once()


if __name__ == '__main__':
    unittest.main(verbosity=2)

#!/usr/bin/env python3
"""Проверки API ИИ-помощника в текстовом и JSON-режимах."""
import json
import unittest
from unittest.mock import patch

import server
from tests.test_remote_analysis import FakeResponse


class AssistantApiTest(unittest.TestCase):
    def test_plain_text_interview_request(self):
        payload = {'choices': [{'message': {'content': 'Здравствуйте! Как проходит ваш рабочий день?'}}]}
        with patch.object(server, 'ANALYSIS_BASE', 'https://llm.test'), \
             patch.object(server, 'ANALYSIS_KEY', 'test-key'), \
             patch.object(server, 'ANALYSIS_MODEL', 'test-model'), \
             patch.object(server.urllib.request, 'urlopen', return_value=FakeResponse(payload)) as call:
            result = server.assistant_chat([{'role': 'user', 'content': 'Задай первый вопрос'}], json_mode=False)
        self.assertEqual(result, 'Здравствуйте! Как проходит ваш рабочий день?')
        body = json.loads(call.call_args.args[0].data)
        self.assertEqual(body['model'], 'test-model')
        self.assertNotIn('response_format', body)

    def test_json_request_has_structured_output(self):
        payload = {'choices': [{'message': {'content': '{"summary":"Готово"}'}}]}
        with patch.object(server, 'ANALYSIS_BASE', 'https://llm.test'), \
             patch.object(server, 'ANALYSIS_KEY', 'test-key'), \
             patch.object(server.urllib.request, 'urlopen', return_value=FakeResponse(payload)) as call:
            result = server.assistant_chat([{'role': 'user', 'content': 'Верни JSON'}], json_mode=True)
        self.assertEqual(result, '{"summary":"Готово"}')
        body = json.loads(call.call_args.args[0].data)
        self.assertEqual(body['response_format'], {'type': 'json_object'})
        self.assertEqual(body['max_tokens'], 12000)
        self.assertEqual(body['reasoning_effort'], 'low')

    def test_remote_is_available_and_local_is_only_fallback(self):
        with patch.object(server, 'ANALYSIS_BASE', 'https://llm.test'), \
             patch.object(server, 'ANALYSIS_KEY', 'test-key'), \
             patch.object(server, 'remote_assistant_chat', side_effect=server.LLMError('down')), \
             patch.object(server, 'ollama_chat', return_value='Локальный резерв') as local:
            self.assertTrue(server.ai_available())
            self.assertEqual(server.assistant_chat([{'role': 'user', 'content': 'Тест'}]), 'Локальный резерв')
        local.assert_called_once()


if __name__ == '__main__':
    unittest.main(verbosity=2)

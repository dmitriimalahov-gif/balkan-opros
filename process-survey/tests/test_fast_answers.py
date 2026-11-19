#!/usr/bin/env python3
"""Сотрудник меньше ждёт: интервьюер знает о документах в разборе, а пустой ответ модели
повторяется один раз вместо ухода в медленный локальный резерв."""
import unittest
from pathlib import Path
from unittest.mock import patch

import knowledge
import server
from test_server import SurveyApiTest
from tests.test_knowledge import make_xlsx

ROOT = Path(__file__).resolve().parents[1]
XLSX_MIME = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'


class PendingDocumentTest(SurveyApiTest):
    def make_doc_with_attachment(self, aid, extra_messages=()):
        code, created = self.create()
        self.assertEqual(code, 200)
        doc = created['doc']
        doc['messages'] = [
            {'role': 'assistant', 'content': 'Приложите журнал приёмки', 'phase': 1},
            {'role': 'user', 'content': 'Прикладываю журнал', 'attachmentIds': [aid]},
            *extra_messages,
        ]
        doc['attachments'] = [{'id': aid, 'kind': 'file', 'name': 'журнал.xlsx', 'mime': XLSX_MIME,
                               'size': 1, 'sha256': 'test', 'questionIndex': 0, 'messageIndex': 1,
                               'question': 'Приложите журнал приёмки', 'createdAt': doc['createdAt']}]
        server.save_doc(doc['id'], doc)
        path = Path(server.DB_PATH).parent / 'attachments' / doc['id'] / aid
        path.parent.mkdir(parents=True)
        make_xlsx(path)
        server.enqueue_knowledge(server.DB_PATH, doc, doc['attachments'][0])
        return doc

    def test_interviewer_announces_document_still_in_analysis(self):
        doc = self.make_doc_with_attachment('d' * 24)
        last = server.turn_messages(doc)[-1]['content']
        self.assertIn('журнал.xlsx', last)
        self.assertIn('на стадии разбора', last)
        self.assertIn('подожд', last)
        self.assertNotIn('Разбор приложенных документов', last)

    def test_announcement_is_not_repeated_on_later_answers(self):
        later = [{'role': 'assistant', 'content': 'Следующий вопрос', 'phase': 1},
                 {'role': 'user', 'content': 'Ответ без документов'}]
        doc = self.make_doc_with_attachment('e' * 24, later)
        messages = server.turn_messages(doc)
        earlier, last = messages[-3]['content'], messages[-1]['content']
        self.assertIn('ещё на стадии разбора', earlier)
        self.assertNotIn('подожд', earlier)
        self.assertNotIn('стадии разбора', last)

    def test_ready_document_replaces_pending_note(self):
        doc = self.make_doc_with_attachment('f' * 24)
        self.assertTrue(knowledge.process_one(server.DB_PATH, lambda prompt: {
            'summary': 'Журнал приёмки сырья по сериям', 'document_type': 'Журнал приёмки сырья'}))
        last = server.turn_messages(doc)[-1]['content']
        self.assertIn('Разбор приложенных документов', last)
        self.assertNotIn('стадии разбора', last)

    def test_unreadable_document_is_reported_to_interviewer(self):
        doc = self.make_doc_with_attachment('a1' * 12)
        with patch.object(knowledge, 'extract_document', side_effect=knowledge.KnowledgeError('image_format_unsupported')):
            self.assertTrue(knowledge.process_one(server.DB_PATH, lambda prompt: {}))
        last = server.turn_messages(doc)[-1]['content']
        self.assertIn('не удалось прочитать', last)
        self.assertNotIn('стадии разбора', last)


class RetryBeforeSlowFallbackTest(unittest.TestCase):
    def remote_configured(self):
        return patch.multiple(server, ANALYSIS_BASE='https://litellm.test', ANALYSIS_KEY='test-key')

    def test_empty_reply_is_retried_once_before_local_fallback(self):
        replies = [server.LLMError('remote_analysis_empty'), 'Следующий вопрос']
        with self.remote_configured(), \
             patch.object(server, 'remote_assistant_chat', side_effect=replies) as remote, \
             patch.object(server, 'ollama_chat') as local:
            self.assertEqual(server.assistant_chat([{'role': 'user', 'content': 'Ответ'}]), 'Следующий вопрос')
        self.assertEqual(remote.call_count, 2)
        local.assert_not_called()

    def test_gateway_error_is_retried(self):
        replies = [server.LLMError('remote_analysis_http_502: <html>'), 'Следующий вопрос']
        with self.remote_configured(), \
             patch.object(server, 'remote_assistant_chat', side_effect=replies) as remote, \
             patch.object(server, 'ollama_chat') as local:
            self.assertEqual(server.assistant_chat([{'role': 'user', 'content': 'Ответ'}]), 'Следующий вопрос')
        self.assertEqual(remote.call_count, 2)
        local.assert_not_called()

    def test_bad_request_goes_to_fallback_without_retry(self):
        with self.remote_configured(), \
             patch.object(server, 'remote_assistant_chat', side_effect=server.LLMError('remote_analysis_http_400: x')) as remote, \
             patch.object(server, 'ollama_chat', return_value='Локальный резерв') as local:
            self.assertEqual(server.assistant_chat([{'role': 'user', 'content': 'Ответ'}]), 'Локальный резерв')
        self.assertEqual(remote.call_count, 1)
        local.assert_called_once()

    def test_document_summary_retries_empty_reply(self):
        replies = [server.LLMError('remote_analysis_empty'), '{"summary": "Готово"}']
        with self.remote_configured(), \
             patch.object(server, 'remote_analysis_chat', side_effect=replies) as remote, \
             patch.object(server, 'ollama_chat') as local:
            self.assertEqual(server.document_summary('Разбери документ')['summary'], 'Готово')
        self.assertEqual(remote.call_count, 2)
        local.assert_not_called()


class ClientWaitCapTest(unittest.TestCase):
    def test_employee_waits_for_analysis_at_most_15_seconds(self):
        page = (ROOT / 'static' / 'index.html').read_text(encoding='utf-8')
        self.assertIn('KNOWLEDGE_WAIT_MS = 15000', page)
        self.assertEqual(page.count('analysisPending:'), 2, 'текст нужен на русском и румынском')
        self.assertIn('на стадии разбора', page)


if __name__ == '__main__':
    unittest.main(verbosity=2)

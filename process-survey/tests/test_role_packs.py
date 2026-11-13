#!/usr/bin/env python3
"""Полнота ролевых профилей и их прохождение через API и экспорт."""
import unittest

import server
from role_packs import DEFAULT_BY_DEPT, ROLE_PACKS, role_coverage, role_key, role_questions
from test_server import SurveyApiTest


class RolePackDataTest(unittest.TestCase):
    def test_all_roles_complete_bilingual_and_referenced(self):
        self.assertEqual(len(ROLE_PACKS), 22)
        self.assertEqual(len(DEFAULT_BY_DEPT), 21)
        ids = set()
        for key, pack in ROLE_PACKS.items():
            with self.subTest(role=key):
                self.assertEqual(len(pack['questions']), 14)
                self.assertGreaterEqual(len(pack['coverage_ru']), 10)
                self.assertTrue(pack['practices'])
                self.assertTrue(pack['title']['ru'] and pack['title']['ro'])
                self.assertTrue(pack['mission']['ru'] and pack['mission']['ro'])
                for field in ('responsibilities', 'decisions', 'documents', 'kpis'):
                    self.assertTrue(pack['profile'][field], field)
                for question in pack['questions']:
                    self.assertNotIn(question['id'], ids)
                    ids.add(question['id'])
                    self.assertTrue(question['id'].startswith(key + '-'))
                    self.assertIn(question['phase'], range(1, 6))
                    self.assertTrue(question['ru'].strip() and question['ro'].strip())
        self.assertEqual(len(ids), 308)

    def test_every_prompt_has_full_role_backbone_in_both_languages(self):
        for key, pack in ROLE_PACKS.items():
            doc = {'dept': pack['dept'], 'roleKey': key, 'position': pack['title']['ru'], 'lang': 'ru'}
            prompt = server.rules_prompt(doc)
            self.assertIn('roleKey=' + key, prompt)
            self.assertIn('референтная модель', prompt)
            self.assertIn('[[Q:%s]]' % pack['questions'][0]['id'], prompt)
            self.assertIn('[[Q:%s]]' % pack['questions'][-1]['id'], prompt)
            self.assertIn('[[1]]', prompt)
            doc['lang'] = 'ro'
            romanian = role_questions(doc, 'ro')
            self.assertEqual(len(romanian), 14)
            self.assertEqual(romanian[0]['text'], pack['questions'][0]['ro'])
            self.assertNotEqual(romanian[0]['text'], pack['questions'][0]['ru'])

    def test_summary_contains_erp_requirement_model(self):
        prompt = server.summary_prompt({'dept': 'quality', 'roleKey': '20', 'position': 'QA', 'lang': 'ru', 'messages': []}, 'ru')
        for field in ('role_key', 'responsibilities', 'decision_rights', 'documents', 'kpis', 'exceptions', 'erp_requirements'):
            self.assertIn(field, prompt)
        self.assertIn('roleKey=20', prompt)


class RoleApiTest(SurveyApiTest):
    def test_explicit_default_and_invalid_role(self):
        code, created = self.request('POST', '/api/interviews', {
            'name': 'Регулятор', 'dept': 'regulatory', 'roleKey': '16', 'position': 'Специалист',
            'lang': 'ru', 'consent': True,
        })
        self.assertEqual(code, 200)
        self.assertEqual(created['doc']['roleKey'], '16')
        self.assertEqual(created['doc']['script']['stage'], 'role')
        code, error = self.request('POST', '/api/interviews', {
            'name': 'Ошибка', 'dept': 'it', 'roleKey': '99', 'position': 'Тест', 'lang': 'ru', 'consent': True,
        })
        self.assertEqual((code, error), (400, {'error': 'fields'}))

    def test_default_role_and_question_key_persist(self):
        code, created = self.create()
        self.assertEqual(code, 200)
        token = created['token']
        self.assertEqual(created['doc']['roleKey'], '15')
        doc = created['doc']
        doc['messages'] = [
            {'role': 'assistant', 'content': 'Вопрос', 'questionKey': '15-01', 'phase': 1},
            {'role': 'user', 'content': 'Ответ'},
        ]
        code, _ = self.request('PUT', '/api/me', {'doc': doc}, token=token)
        self.assertEqual(code, 200)
        code, loaded = self.request('GET', '/api/me', token=token)
        self.assertEqual(loaded['doc']['messages'][0]['questionKey'], '15-01')
        coverage = role_coverage(loaded['doc'])
        self.assertEqual((coverage['asked'], coverage['total']), (1, 14))
        doc['roleKey'] = '99'
        cleaned = server.clean_doc(doc, loaded['doc'])
        self.assertEqual(cleaned['roleKey'], '15')

    def test_multiple_roles_share_backbone_and_coverage(self):
        code, created = self.request('POST', '/api/interviews', {
            'name': 'Две функции', 'dept': 'prod_dir', 'roleKey': '01', 'roleKeys': ['01', '20'],
            'position': 'Директор и качество', 'lang': 'ru', 'consent': True,
        })
        self.assertEqual(code, 200)
        doc = created['doc']
        self.assertEqual(doc['roleKey'], '01')
        self.assertEqual(doc['roleKeys'], ['01', '20'])
        prompt = server.rules_prompt(doc)
        self.assertIn('roleKeys=01,20', prompt)
        self.assertIn('[[Q:01-01]]', prompt)
        self.assertIn('[[Q:20-01]]', prompt)
        doc['messages'] = [
            {'role': 'assistant', 'content': 'Первый', 'questionKey': '01-01'},
            {'role': 'assistant', 'content': 'Второй', 'questionKey': '20-01'},
        ]
        coverage = role_coverage(doc)
        self.assertEqual((coverage['asked'], coverage['total']), (2, 28))
        self.assertEqual(coverage['roleKeys'], ['01', '20'])
        code, error = self.request('POST', '/api/interviews', {
            'name': 'Ошибка', 'dept': 'it', 'roleKeys': ['01', '99'], 'position': 'Тест', 'lang': 'ru', 'consent': True,
        })
        self.assertEqual((code, error), (400, {'error': 'fields'}))


if __name__ == '__main__':
    unittest.main(verbosity=2)

#!/usr/bin/env python3
"""Персонализация вопросов по свободному описанию работы."""
import unittest

from about_analysis import analyze_about, analyze_about_with_llm, prioritize_questions
import server
from test_server import SurveyApiTest


class AboutAnalysisTest(unittest.TestCase):
    def test_rules_extract_real_activities_systems_and_documents(self):
        result = analyze_about('Каждый день сверяю остатки и готовлю отчёт в Excel. Проверяю BOM и выдаю сырьё на склад.')
        labels = [item['label'] for item in result['activities']]
        self.assertIn('Сверки и согласование данных', labels)
        self.assertIn('Отчёты и сводки', labels)
        self.assertIn('Excel', result['systems'])
        self.assertIn('BOM', result['documents'])
        self.assertEqual(result['source'], 'rules')
        for item in result['activities']:
            for evidence in item['evidence']:
                self.assertIn(evidence.lower(), 'каждый день сверяю остатки и готовлю отчёт в excel. проверяю bom и выдаю сырьё на склад.')

    def test_llm_cannot_invent_activities_without_evidence(self):
        text = 'Проверяю записи операторов.'
        result = analyze_about_with_llm(text, 'ru', ['03'], lambda prompt: {
            'summary': 'Контроль записей',
            'activities': [{'key': 'records', 'label': 'Проверка записей', 'evidence': ['Проверяю записи операторов.']}],
            'systems': ['ERP'], 'documents': ['журнал'], 'keywords': ['записи'],
        })
        self.assertEqual(result['source'], 'ollama')
        self.assertEqual(result['activities'][0]['label'], 'Проверка записей')
        rejected = analyze_about_with_llm(text, 'ru', ['03'], lambda prompt: {
            'activities': [{'key': 'fake', 'label': 'Выдуманный процесс', 'evidence': ['Несуществующая цитата']}],
        })
        self.assertEqual(rejected['source'], 'rules')

    def test_relevance_stays_inside_phase(self):
        questions = [
            {'id': 'a', 'phase': 1, 'text': 'Какие закупки вы выполняете?'},
            {'id': 'b', 'phase': 1, 'text': 'Какие отчёты вы готовите?'},
            {'id': 'c', 'phase': 2, 'text': 'Какие поставщики участвуют?'},
        ]
        analysis = {'activities': [{'label': 'Отчёты', 'evidence': ['Готовлю отчёты']}]}
        ordered = prioritize_questions(questions, analysis)
        self.assertEqual(ordered[0]['id'], 'b')
        self.assertEqual(ordered[1]['id'], 'a')
        self.assertEqual(ordered[2]['id'], 'c')

    def test_romanian_activity_extraction(self):
        result = analyze_about('Verific stocul și pregătesc un raport în Excel pentru calitate.')
        self.assertTrue(result['activities'])
        self.assertIn('Excel', result['systems'])
        self.assertIn('calitate', result['keywords'])


class AboutApiTest(SurveyApiTest):
    def test_about_is_saved_and_used_in_prompt_and_export_model(self):
        about = 'Сверяю остатки и готовлю отчёт в Excel. Проверяю BOM и согласую изменения.'
        code, created = self.request('POST', '/api/interviews', {
            'name': 'Сотрудник', 'dept': 'planning', 'position': 'Планировщик',
            'roleKey': '02', 'about': about, 'lang': 'ru', 'consent': True,
        })
        self.assertEqual(code, 200)
        doc = created['doc']
        self.assertEqual(doc['about'], about)
        self.assertEqual(doc['aboutAnalysis']['source'], 'rules')
        self.assertTrue(doc['aboutAnalysis']['activities'])
        prompt = server.rules_prompt(doc)
        self.assertIn(about, prompt)
        self.assertIn('Извлечённые только из этого описания занятия', prompt)
        self.assertIn('Сначала задай вопросы о конкретных занятиях', prompt)
        summary_prompt = server.summary_prompt(doc, 'ru')
        self.assertIn(about, summary_prompt)
        self.assertIn('Извлечённые занятия', summary_prompt)
        self.assertIn('"summary"', summary_prompt)

    def test_answered_questions_are_not_repeated(self):
        doc = {'dept': 'planning', 'roleKey': '02', 'lang': 'ru', 'messages': [
            {'role': 'assistant', 'content': 'Первый вопрос', 'questionKey': '02-01'},
            {'role': 'user', 'content': 'Мой ответ'},
        ]}
        prompt = server.rules_prompt(doc)
        self.assertNotIn('[[Q:02-01]]', prompt)
        self.assertIn('[[Q:02-02]]', prompt)
        self.assertIn('Уже отвечено: 02-01', prompt)
        self.assertIn('Не задавай эти вопросы повторно', prompt)


if __name__ == '__main__':
    unittest.main(verbosity=2)

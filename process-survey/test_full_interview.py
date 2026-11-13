#!/usr/bin/env python3
"""Полный тестовый цикл интервью с настоящей моделью на временной базе."""
import json
import re
import tempfile
import threading
import urllib.error
import urllib.request
from datetime import datetime, timezone
from http.server import ThreadingHTTPServer
from pathlib import Path

import server

ROOT = Path(__file__).parent
REPORT = ROOT / 'run' / 'full-interview-test-report.json'


def now_iso():
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + 'Z'


def parse_turn(text):
    done = '[[DONE]]' in text.upper()
    phase_match = re.search(r'\[\[([1-5])\]\]', text)
    question_match = re.search(r'\[\[Q:([A-Za-z0-9-]+)\]\]', text, re.I)
    options_match = re.search(r'\[\[OPTIONS\s+(one|many)\s*:\s*([\s\S]*?)\]\]', text, re.I)
    options = []
    mode = 'many'
    if options_match:
        mode = options_match.group(1).lower()
        options = [item.strip() for item in options_match.group(2).split('|') if item.strip()]
    content = re.sub(r'\[\[Q:[A-Za-z0-9-]+\]\]', '', text, flags=re.I)
    content = re.sub(r'\[\[(?:DONE|[1-5])\]\]', '', content, flags=re.I)
    content = re.sub(r'\[\[OPTIONS\s+(?:one|many)\s*:[\s\S]*?\]\]', '', content, flags=re.I).strip()
    return {
        'done': done,
        'phase': int(phase_match.group(1)) if phase_match else 1,
        'questionKey': question_match.group(1) if question_match else None,
        'options': options,
        'mode': mode,
        'content': content or 'Спасибо!',
    }


def synthetic_answer(question, options):
    q = question.lower()
    picked = []
    if options:
        if any(word in q for word in ('программ', 'систем', 'инструмент')):
            picked = [x for x in options if x.lower() in ('1с', 'excel', 'почта', 'erp')][:3]
        elif any(word in q for word in ('ошиб', 'рутин', 'однообраз', 'передел', 'не так')):
            picked = options[:2]
        elif any('да' == x.lower().strip(' .') for x in options):
            picked = [next((x for x in options if x.lower().strip(' .') == 'да'), options[0])]
        elif 'часто' in q or 'частот' in q:
            picked = [next((x for x in options if 'ежеднев' in x.lower()), options[0])]
        else:
            picked = [options[0]]

    if 'пример' in q or 'недавн' in q:
        own = ('На прошлой неделе я два часа переносил данные смен из трёх Excel-файлов в сводный отчёт, '
               'затем нашёл несовпадение и повторно проверил исходники.')
    elif any(word in q for word in ('сколько времени', 'сколько минут', 'длительн', 'как долго')):
        own = 'Ежедневная проверка занимает около 30 минут, а сводный отчёт — примерно два часа.'
    elif 'часто' in q or 'частот' in q:
        own = 'Проверяю данные ежедневно, а сводный отчёт готовлю раз в неделю по пятницам.'
    elif any(word in q for word in ('программ', 'систем', 'инструмент')):
        own = 'Использую 1С, Excel и почту; часть первичных данных приходит в бумажных журналах.'
    elif any(word in q for word in ('откуда', 'от кого', 'исходн')):
        own = 'Исходные данные присылают мастера смен и склад в Excel-файлах через почту.'
    elif any(word in q for word in ('кому', 'передаёт', 'передаете', 'передаёте', 'результат')):
        own = 'Проверенный результат передаю руководителю производства и бухгалтерии.'
    elif any(word in q for word in ('соглас', 'подпис')):
        own = 'Отчёт согласует начальник участка, обычно ожидание занимает от одного часа до одного дня.'
    elif any(word in q for word in ('отдел', 'взаимодейств', 'стык')):
        own = 'Работаю с производством, складом и бухгалтерией; чаще всего жду уточнения количества от склада.'
    elif any(word in q for word in ('ошиб', 'рутин', 'однообраз', 'передел', 'не так', 'боль')):
        own = 'Больше всего времени отнимает ручной перенос между файлами; иногда теряются версии и приходится переделывать.'
    elif any(word in q for word in ('опыт', 'человек', 'решени')):
        own = 'Человек должен оценивать расхождения и принимать решение в нестандартных случаях.'
    elif any(word in q for word in ('помощник', 'автомат', 'отдали')):
        own = 'Помощнику отдал бы сбор файлов, проверку форматов и формирование чернового сводного отчёта.'
    elif any(word in q for word in ('роль', 'недел', 'отвеча', 'обязан')):
        own = ('Отвечаю за проверку производственных данных и отчётность. Ежедневно сверяю данные смен, '
               'еженедельно готовлю сводный отчёт, в конце месяца проверяю итоги.')
    elif any(word in q for word in ('задач', 'дела', 'процесс')):
        own = ('Три основные задачи: ежедневная проверка данных смен, сведение Excel-таблиц '
               'и еженедельная подготовка отчёта для руководителя.')
    else:
        own = ('В обычном случае выполняю задачу ежедневно в 1С и Excel примерно 30 минут, '
               'проверяю результат и передаю его руководителю.')
    content = '; '.join(picked) + (' — ' if picked else '') + own
    return content, picked, own


class FullInterviewTest:
    def __init__(self):
        self.temp = None
        self.httpd = None
        self.thread = None
        self.base = None

    def start(self):
        if not server.ai_available():
            raise RuntimeError('Локальная модель недоступна')
        self.temp = tempfile.TemporaryDirectory(prefix='full-interview-', dir=ROOT / 'run')
        root = Path(self.temp.name)
        server.DB_PATH = str(root / 'survey.db')
        server.ADMIN_FILE = str(root / 'admin.txt')
        server.TUNNEL_LOG = str(root / 'tunnel.log')
        server.PUSHED_FILE = str(root / 'pushed-url')
        Path(server.ADMIN_FILE).write_text('full-test-admin\n', encoding='utf-8')
        Path(server.TUNNEL_LOG).write_text('https://test.invalid\n', encoding='utf-8')
        Path(server.PUSHED_FILE).write_text(server.STABLE_URL + '\n', encoding='utf-8')
        server._hits = {}
        server.init_db()
        self.httpd = ThreadingHTTPServer(('127.0.0.1', 0), server.Handler)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        self.base = 'http://127.0.0.1:%d' % self.httpd.server_port
        print('Изолированный сервер запущен, временная база создана', flush=True)

    def close(self):
        if self.httpd:
            self.httpd.shutdown()
            self.httpd.server_close()
        if self.thread:
            self.thread.join(timeout=5)
        if self.temp:
            self.temp.cleanup()
        print('Изолированный сервер остановлен, временная база удалена', flush=True)

    def request(self, method, path, body=None, token=None, admin=None, timeout=650):
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
            with urllib.request.urlopen(req, timeout=timeout) as response:
                return response.status, json.load(response)
        except urllib.error.HTTPError as error:
            return error.code, json.load(error)

    def expect(self, method, path, expected=200, **kwargs):
        code, payload = self.request(method, path, **kwargs)
        if code != expected:
            raise AssertionError('%s %s: ожидался %s, получен %s: %s' % (method, path, expected, code, payload))
        return payload

    def run(self):
        created = self.expect('POST', '/api/interviews', body={
            'name': 'Тестовый сотрудник',
            'dept': 'planning',
            'position': 'Специалист по производственным отчётам',
            'about': 'Ежедневно сверяю остатки и готовлю отчёт в Excel. Проверяю BOM и планирую производство.',
            'lang': 'ru',
            'consent': True,
            'mode': 'ai',
        })
        token = created['token']
        doc = created['doc']
        if doc['mode'] != 'ai':
            raise AssertionError('Интервью создано не в режиме ИИ')
        if doc.get('roleKey') != '02':
            raise AssertionError('Не назначена роль планировщика: %s' % doc.get('roleKey'))
        if not doc.get('aboutAnalysis', {}).get('activities'):
            raise AssertionError('Описание работы не разобрано: нет занятий')

        options_turns = 0
        multi_answer_turns = 0
        phases = []
        done = False
        for turn_number in range(1, 61):
            raw = self.expect('POST', '/api/me/turn', body={}, token=token)['text']
            turn = parse_turn(raw)
            if turn['phase'] not in phases:
                phases.append(turn['phase'])
            assistant = {
                'role': 'assistant',
                'content': turn['content'],
                'phase': turn['phase'],
                'questionKey': turn['questionKey'],
                't': now_iso(),
            }
            if turn['options']:
                assistant['options'] = turn['options']
                assistant['mode'] = turn['mode']
                options_turns += 1
            doc['messages'].append(assistant)
            doc['phase'] = turn['phase']
            print('Вопрос %02d | этап %d | вариантов: %d' % (
                turn_number, turn['phase'], len(turn['options'])), flush=True)
            if turn['done']:
                done = True
                self.expect('PUT', '/api/me', body={'doc': doc}, token=token)
                break

            answer, picked, own = synthetic_answer(turn['content'], turn['options'])
            if len(picked) > 1:
                multi_answer_turns += 1
            doc['messages'].append({
                'role': 'user', 'content': answer, 'picked': picked, 'own': own, 't': now_iso(),
            })
            self.expect('PUT', '/api/me', body={'doc': doc}, token=token)

        if not done:
            raise AssertionError('Интервью не завершилось за 60 вопросов')
        user_answers = sum(m['role'] == 'user' for m in doc['messages'])
        if user_answers < 5:
            raise AssertionError('Слишком короткое интервью: %s ответов' % user_answers)
        expected_questions = {q['id'] for q in server.role_questions(doc)}
        asked_questions = {m.get('questionKey') for m in doc['messages'] if m.get('role') == 'assistant'}
        missing_questions = sorted(expected_questions - asked_questions)
        if missing_questions:
            raise AssertionError('Модель пропустила базовые вопросы: %s' % ', '.join(missing_questions))
        print('Интервью завершено моделью; ответов сотрудника: %d' % user_answers, flush=True)

        summary = self.expect('POST', '/api/me/summary', body={}, token=token)['summary']
        if not isinstance(summary.get('role_summary'), str) or not summary['role_summary'].strip():
            raise AssertionError('В резюме нет role_summary')
        if not isinstance(summary.get('processes'), list):
            raise AssertionError('В резюме нет списка processes')
        for field in ('responsibilities', 'decision_rights', 'documents', 'kpis', 'exceptions', 'erp_requirements'):
            if not isinstance(summary.get(field), list):
                raise AssertionError('В резюме нет списка ' + field)
        if summary.get('role_key') != '02':
            raise AssertionError('В резюме неверная role_key: %s' % summary.get('role_key'))
        doc['summary'] = summary
        doc['summaryBy'] = 'employee'
        doc['summaryAt'] = now_iso()
        doc['status'] = 'done'
        doc['finishedAt'] = now_iso()
        doc['submittedAt'] = now_iso()
        self.expect('PUT', '/api/me', body={'doc': doc}, token=token)

        loaded = self.expect('GET', '/api/me', token=token)['doc']
        if loaded['status'] != 'done' or loaded.get('summary') != summary:
            raise AssertionError('Резюме или финальный статус не сохранились')
        admin_docs = self.expect('GET', '/api/admin/interviews', admin='full-test-admin')['interviews']
        if len(admin_docs) != 1 or admin_docs[0]['id'] != doc['id']:
            raise AssertionError('Панель руководителя не видит тестовое интервью')

        report = {
            'ok': True,
            'isolatedDatabase': True,
            'completedByModel': done,
            'userAnswers': user_answers,
            'assistantMessages': sum(m['role'] == 'assistant' for m in doc['messages']),
            'questionsWithOptions': options_turns,
            'answersWithMultipleOptions': multi_answer_turns,
            'roleBaseQuestions': len(expected_questions & asked_questions),
            'roleBaseQuestionsTotal': len(expected_questions),
            'phasesSeen': phases,
            'summaryProcesses': len(summary['processes']),
            'summarySaved': True,
            'finalStatus': loaded['status'],
        }
        REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)


if __name__ == '__main__':
    test = FullInterviewTest()
    try:
        test.start()
        test.run()
    finally:
        test.close()

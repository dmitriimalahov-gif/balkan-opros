#!/usr/bin/env python3
"""Сервер опроса «Карта процессов Balkan».

Публичная анкета для сотрудников (без входа и приглашений) + ИИ-интервьюер на локальной Ollama
+ панель руководителя и локальная база знаний разобранных документов.

Приватность:
  * каждый респондент получает случайный токен; в БД хранится только его sha256;
  * читать и менять интервью можно только своим токеном; списка интервью без пароля нет;
  * промпты собираются на сервере из сохранённого интервью — API не годится как чат с моделью.

Запуск: python3 server.py   (порт SURVEY_PORT, по умолчанию 8795, слушает только 127.0.0.1)
"""
import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import shutil
import sqlite3
import ssl
import certifi
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, quote, unquote, urlparse
from role_packs import ROLE_PACKS, role_key, role_keys, role_pack, role_packs, role_title, role_questions
from about_analysis import analyze_about, prioritize_questions
from owner_voice import voice_available, request_voice, voice_audio_path
from knowledge import (KnowledgeError, init_knowledge, enqueue_knowledge, sync_knowledge, delete_knowledge,
                       knowledge_status, list_knowledge, knowledge_worker)

BASE = os.path.dirname(os.path.abspath(__file__))
PORT = int(os.environ.get('SURVEY_PORT', '8795'))
OLLAMA = os.environ.get('SURVEY_OLLAMA', 'http://127.0.0.1:11434')
MODEL = os.environ.get('SURVEY_MODEL', 'qwen3.5:9b')
ANALYSIS_BASE = os.environ.get('SURVEY_ANALYSIS_BASE') or os.environ.get('LLM_BASE_URL', '')
ANALYSIS_KEY = os.environ.get('SURVEY_ANALYSIS_KEY') or os.environ.get('LLM_API_KEY', '')
ANALYSIS_MODEL = os.environ.get('SURVEY_ANALYSIS_MODEL', 'qwen3.8-flash-next-iq3_s')
ANALYSIS_TIMEOUT = int(os.environ.get('SURVEY_ANALYSIS_TIMEOUT', '120'))
ROUTER_MODELS = {'auto'}  # алиасы автоматической маршрутизации шлюза LiteLLM (OpenCode)
# Фото и сканы документов на сервере (без macOS Vision) читает модель с распознаванием изображений.
VISION_MODEL = os.environ.get('SURVEY_VISION_MODEL') or ANALYSIS_MODEL
MAX_VISION_IMAGE = 15 * 1024 * 1024
VISION_PROMPT = ('Это фото или скан рабочего документа фармацевтического производства. Перепиши весь видимый текст '
                 'дословно, сохраняя строки; колонки таблиц разделяй символом |. Если текста почти нет, кратко опиши, '
                 'что изображено. Без пояснений и без markdown.')
DB_PATH = os.path.join(BASE, 'data', 'survey.db')
ADMIN_FILE = os.path.join(BASE, 'ADMIN_PASSWORD.txt')
TUNNEL_LOG = os.path.join(BASE, 'run', 'tunnel.log')
INDEX_HTML = os.path.join(BASE, 'static', 'index.html')
# Постоянная ссылка (как у Helper): страница на GitHub Pages встраивает опрос и берёт текущий адрес туннеля
# из current.json, который обновляет watchdog.sh.
STABLE_URL = os.environ.get('SURVEY_STABLE_URL', 'https://dmitriimalahov-gif.github.io/balkan-opros/')
STABLE_ORIGIN = 'https://dmitriimalahov-gif.github.io'
PUSHED_FILE = os.path.join(BASE, 'run', 'pushed-url')


def stable_url():
    """Постоянный адрес — только после первой успешной публикации current.json (иначе там 404)."""
    return STABLE_URL if os.path.exists(PUSHED_FILE) else ''

MAX_BODY = 600_000
MAX_DOC = 450_000
MAX_FILE = 500 * 1024 * 1024
UPLOAD_CHUNK = 8 * 1024 * 1024  # меньше ограничения quick tunnel; большие файлы идут частями
MAX_FILES_PER_QUESTION = 5
MAX_ATTACHMENTS_PER_INTERVIEW = 100
MAX_ATTACHMENT_BYTES_PER_INTERVIEW = 5 * 1024 * 1024 * 1024
FILE_TYPES = {
    '.xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    '.xls': 'application/vnd.ms-excel',
    '.csv': 'text/csv',
    '.pdf': 'application/pdf',
    '.doc': 'application/msword',
    '.docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.png': 'image/png', '.gif': 'image/gif',
    '.webp': 'image/webp', '.heic': 'image/heic', '.heif': 'image/heif',
    '.bmp': 'image/bmp', '.tif': 'image/tiff', '.tiff': 'image/tiff',
}
MAX_TURNS = 90          # ответов ИИ на одно интервью
# Контекст = как у общего раннера Ollama на этом Mac (Алама, JARVIS, монитор — 16384): другой num_ctx
# перезагружает модель (десятки секунд) и выбивает её у соседей.
NUM_CTX = 16384
ANALYSIS_CHUNK = 24_000  # символов резюме на один вызов анализа
LLM_SEM = threading.Semaphore(2)
DB_LOCK = threading.Lock()
_knowledge_stop = None
_knowledge_thread = None


def remote_assistant_chat(messages, json_mode=False, temperature=0.4, timeout=None, max_tokens=4000, reasoning_effort=None,
                          model=None):
    model = model or ANALYSIS_MODEL
    body = {'model': model, 'messages': messages, 'max_tokens': max_tokens}
    # Роутер шлюза сам выбирает конечную модель, а её ограничения заранее неизвестны (например, часть
    # моделей отвергает temperature при рассуждении) — temperature и reasoning_effort оставляем ему.
    if model not in ROUTER_MODELS:
        body['temperature'] = temperature
        if reasoning_effort:
            body['reasoning_effort'] = reasoning_effort
    if json_mode:
        body['response_format'] = {'type': 'json_object'}
    request = urllib.request.Request(
        ANALYSIS_BASE.rstrip('/') + '/v1/chat/completions', json.dumps(body, ensure_ascii=False).encode('utf-8'),
        {'Content-Type': 'application/json', 'Authorization': 'Bearer ' + ANALYSIS_KEY},
    )
    context = ssl.create_default_context(cafile=certifi.where())
    try:
        with urllib.request.urlopen(request, context=context, timeout=timeout or ANALYSIS_TIMEOUT) as response:
            payload = json.load(response)
    except urllib.error.HTTPError as error:
        detail = error.read().decode('utf-8', errors='replace')[:1000]
        raise LLMError('remote_analysis_http_%s: %s' % (error.code, detail)) from error
    except Exception as error:
        raise LLMError('remote_analysis_unavailable: ' + type(error).__name__ + ': ' + str(error)[:140])
    try:
        content = payload['choices'][0]['message']['content']
    except (KeyError, IndexError, TypeError) as error:
        raise LLMError('remote_analysis_invalid_response') from error
    if isinstance(content, list):
        content = ''.join(str(part.get('text') or '') if isinstance(part, dict) else str(part) for part in content)
    if not isinstance(content, str) or not content.strip():
        raise LLMError('remote_analysis_empty')
    return content


def image_mime(data):
    """Тип изображения по сигнатуре: вложения хранятся на диске без расширения."""
    if data[:3] == b'\xff\xd8\xff':
        return 'image/jpeg'
    if data[:8] == b'\x89PNG\r\n\x1a\n':
        return 'image/png'
    if data[:4] == b'GIF8':
        return 'image/gif'
    if data[:4] == b'RIFF' and data[8:12] == b'WEBP':
        return 'image/webp'
    return ''


def remote_image_text(path):
    # Короткие коды KnowledgeError попадают в карточку документа; подробности сбоя шлюза — только в журнал.
    if os.path.getsize(path) > MAX_VISION_IMAGE:
        raise KnowledgeError('image_too_large')
    with open(path, 'rb') as source:
        data = source.read()
    mime = image_mime(data)
    if not mime:
        raise KnowledgeError('image_format_unsupported')
    content = [{'type': 'text', 'text': VISION_PROMPT},
               {'type': 'image_url', 'image_url': {'url': 'data:%s;base64,%s' % (mime, base64.b64encode(data).decode('ascii'))}}]
    try:
        text = remote_assistant_chat([{'role': 'user', 'content': content}], timeout=180, max_tokens=4000, model=VISION_MODEL)
    except LLMError as error:
        print('VISION_API_FAILED', str(error)[:160], flush=True)
        raise KnowledgeError('vision_unavailable') from error
    print('VISION_API_MODEL', VISION_MODEL, flush=True)
    return text


def prompt_safe(value, limit):
    """Текст из документа не должен подделывать служебные пометки интервьюера вида [[Q: …]]."""
    return re.sub(r'\s+', ' ', str(value or '')).replace('[', '(').replace(']', ')').strip()[:limit]


def knowledge_image_reader():
    return remote_image_text if ANALYSIS_BASE and ANALYSIS_KEY else None


def remote_analysis_chat(prompt):
    return remote_assistant_chat([
        {'role': 'system', 'content': 'Отвечай только валидным JSON без markdown и пояснений вне JSON.'},
        {'role': 'user', 'content': prompt},
    ], json_mode=True, temperature=0.2)


# Быстрые сбои шлюза (пустой ответ роутера, 502–504) повторяем один раз: это секунды, а резерв Ollama на CPU — минуты.
RETRYABLE_REMOTE_ERRORS = ('remote_analysis_empty', 'remote_analysis_invalid_response',
                           'remote_analysis_http_502', 'remote_analysis_http_503', 'remote_analysis_http_504')


def remote_with_retry(call):
    try:
        return call()
    except LLMError as error:
        if not str(error).startswith(RETRYABLE_REMOTE_ERRORS):
            raise
        print('ASSISTANT_API_RETRY', str(error)[:80], flush=True)
        return call()


def assistant_chat(messages, json_mode=False, temperature=0.4, timeout=300, max_tokens=None, reasoning_effort=None):
    if ANALYSIS_BASE and ANALYSIS_KEY:
        try:
            result = remote_with_retry(lambda: remote_assistant_chat(
                messages, json_mode=json_mode, temperature=temperature, timeout=timeout,
                max_tokens=max_tokens or (12000 if json_mode else 4000),
                reasoning_effort=reasoning_effort or ('low' if json_mode else None)))
            print('ASSISTANT_API_MODEL', ANALYSIS_MODEL, flush=True)
            return result
        except Exception as error:
            print('ASSISTANT_API_FALLBACK', str(error)[:160], flush=True)
    return ollama_chat(messages, json_mode=json_mode, temperature=temperature, timeout=timeout)


def document_summary(prompt):
    if ANALYSIS_BASE and ANALYSIS_KEY:
        try:
            result = parse_json(remote_with_retry(lambda: remote_analysis_chat(prompt)))
            print('ANALYSIS_API_MODEL', ANALYSIS_MODEL, flush=True)
            return result
        except Exception as error:
            print('ANALYSIS_API_FALLBACK', str(error)[:160], flush=True)
    return parse_json(ollama_chat([{'role': 'user', 'content': prompt}], json_mode=True, temperature=0.2, timeout=120))


def start_knowledge_worker(summarizer=None):
    global _knowledge_stop, _knowledge_thread
    if _knowledge_thread and _knowledge_thread.is_alive():
        return
    _knowledge_stop = threading.Event()
    _knowledge_thread = threading.Thread(target=knowledge_worker,
                                         args=(DB_PATH, summarizer or document_summary, _knowledge_stop, knowledge_image_reader()),
                                         name='knowledge-worker', daemon=True)
    _knowledge_thread.start()


def stop_knowledge_worker():
    global _knowledge_stop, _knowledge_thread
    if _knowledge_stop:
        _knowledge_stop.set()
    if _knowledge_thread:
        _knowledge_thread.join(timeout=5)
    _knowledge_stop = None
    _knowledge_thread = None


DEPTS = {
    'mgmt': 'Руководство компании', 'prod_dir': 'Производство — руководство', 'planning': 'Планирование производства',
    'prod_area': 'Производственный участок (мастер, начальник смены)', 'operator': 'Оператор производства',
    'tech': 'Технология и НСИ (составы, рецептуры)', 'quality': 'Качество (ОКК, QA/QC)',
    'regulatory': 'Регистрация и регуляторика', 'wh_raw': 'Склад сырья и материалов', 'wh_fg': 'Склад готовой продукции',
    'procurement': 'Закупки', 'packaging': 'Упаковка и печать (макеты, ножи)', 'sales': 'Продажи',
    'crm': 'Работа с клиентами (CRM)', 'marketing': 'Маркетинг', 'logistics': 'Логистика и отгрузка',
    'finance': 'Финансы и бухгалтерия', 'analytics': 'Аналитика и отчётность', 'hr': 'Кадры',
    'it': 'ИТ и администрирование', 'other': 'Другое',
}
STATUSES = {'in_progress', 'review', 'done'}

COMPANY = ('Balkan Pharmaceuticals — фармацевтическое производство в Молдове: лекарства и БАДы, собственные бренды '
           'и контрактное производство (Private Label). Упаковку и инструкции печатают подрядчики. В работе используются '
           '1С, Excel, почта, ERP, бумажные журналы и документы GMP.')

WELCOME_VOICE = {
    'ru': 'Здравствуйте! Добро пожаловать на карту процессов Балкан. Заполните короткую форму и нажмите «Начать интервью». '
          'Расскажите о своей работе — вместе мы найдём, что можно упростить.',
    'ro': 'Bună ziua! Alegeți departamentul și funcția, apoi apăsați «Începe interviul». '
          'Povestiți-ne despre munca dumneavoastră.',
}


def now_iso():
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + 'Z'


# ---------- промпты ----------

def role_interview_prompt(doc):
    """Ролевой каркас: референс направляет, но не подменяет фактические ответы."""
    packs = role_packs(doc)
    lang = doc.get('lang') if doc.get('lang') in ('ru', 'ro') else 'ru'
    asked = {m.get('questionKey') for m in doc.get('messages') or [] if isinstance(m, dict) and m.get('questionKey')}
    remaining = [q for q in role_questions(doc, lang) if q['id'] not in asked]
    all_questions = prioritize_questions(remaining, doc.get('aboutAnalysis'))
    questions = all_questions[:3]
    lines = [
        'Подтверждённые сотрудником функции: ' + role_title(doc, lang) + ' (roleKey=' + role_key(doc) + '; roleKeys=' + ','.join(role_keys(doc)) + ').',
        'Первая функция — основная, остальные — дополнительные. При противоречии сначала уточняй распределение работы между ними; '
        'не дублируй общие процессы, но закрой обязательные темы каждой функции.',
        'Это референтная модель, а не факты о Balkan. Не зачитывай список и не приписывай сотруднику обязанности. '
        'Если тема не относится к его работе, уточни почему и отметь «не применимо», не выдумывая процесс.',
    ]
    if asked:
        lines.append('Уже отвечено: ' + ', '.join(sorted(asked)) + '. Не задавай эти вопросы повторно и не перефразируй их. '
                     'Новый вопрос разрешён только по недостающему факту, исправлению или новому примеру.')
    if doc.get('about'):
        analysis = doc.get('aboutAnalysis') or {}
        analysis_brief = {key: (analysis.get(key) or [])[:8] for key in ('activities', 'systems', 'documents')}
        lines.extend([
            'Описание работы сотрудника своими словами: «' + doc['about'][:1200] + '».',
            'Извлечённые только из этого описания занятия: ' + json.dumps(analysis_brief, ensure_ascii=False) + '.',
            'Сначала задай вопросы о конкретных занятиях из описания: процесс, входы, выходы, частота, длительность, документы, '
            'решения и исключения. Ссылайся на них естественно, не копируй текст дословно. Если оно противоречит выбранной функции, '
            'уточни распределение работы, а не отвергай ответ сотрудника. Затем закрой все обязательные темы.',
        ])
    for pack in packs:
        lines.extend([
            'Функция «' + pack['title'][lang] + '»: ' + pack['mission'][lang][:400],
            'Международные ориентиры: ' + ', '.join(pack['practices'][:4]) + '.',
            'Обязательные темы: ' + '; '.join(pack['coverage_ru']) + '.',
        ])
    lines.append('Базовые вопросы с идентификаторами (задавай естественно, адаптируй к предыдущим ответам и добавляй уточнения):')
    lines.extend('[[Q:%s]] [[%d]] %s' % (q['id'], q['phase'], q['text']) for q in questions)
    lines.append('Карта всех обязательных тем: ' + ' '.join('[[Q:%s]]' % q['id'] for q in all_questions))
    lines.extend([
        'Перед базовым вопросом ставь его идентификатор [[Q:…]] и этап [[1]]–[[5]], как в списке. '
        'Для уточнения используй тот же идентификатор с буквой a, b или c.',
        'Для каждой важной темы выясняй: инициатор, проверяющий, утверждающий, исполнитель, документ и версия, статус, срок, '
        'получатель, исключение и доказательство. Проси реальные примеры и приложения, но не конфиденциальные данные.',
        'Если должность руководящая, обязательно раскрой лимиты, запреты, делегирование, заместителей и контроль результата. '
        'Если исполнительская — фактические действия, время, качество, ошибки и передачу результата.',
        'Завершай только после закрытия всех базовых тем и пяти этапов (обычно 20–35 вопросов на каждую функцию). '
        'Не завершай просто потому, что заданы все вопросы списка: проверь, что ответы конкретны и содержат доказательства.',
    ])
    return '\n'.join(lines)


def rules_prompt(doc):
    lang_line = ('Язык интервью: румынский (limba română). Все твои сообщения — только на румынском, обращайся на «dumneavoastră».'
                 if doc.get('lang') == 'ro' else 'Язык интервью: русский. Все твои сообщения — только на русском, обращайся на «вы».')
    return '\n'.join([
        'Ты — интервьюер по рабочим процессам. Компания: ' + COMPANY,
        'Цель: факты о роли, задачах, стыках, документах и рутине. Это не оценка и не проверка человека.',
        'Собеседник: %s; отдел: %s; должность: %s.' % (doc.get('name', ''), DEPTS.get(doc.get('dept'), '—'), doc.get('position', '')),
        lang_line,
        role_interview_prompt(doc),
        'Формат: один короткий вопрос (1–2 предложения), без markdown. Почти всегда добавляй последней строкой '
        '[[OPTIONS many: 3–6 конкретных вариантов до 5 слов]]. Не предлагай «Другое».',
        'Этапы строго по порядку: 1 — роль и обычная неделя; 2 — 3–5 частых задач (частота, время, входы/выходы, '
        'системы, документы, ошибки, реальный пример); 3 — стыки, согласования и подписи; 4 — рутина, ошибки и переделки; '
        '5 — опыт, решения человека и что делегировать помощнику.',
        'Не повторяй уже заданное; максимум два уточнения подряд. Факты и примеры важнее предположений. Не предлагай '
        'решения и не оценивай людей. Не спрашивай секреты и не повторяй их.',
        'Сообщение начинай с [[Q:…]] и этапа [[1]]–[[5]]. После всех этапов и тем: [[DONE]] и одно предложение '
        'благодарности. Для дополнения: 1–3 уточнения и снова [[DONE]].',
        'Каждый ход, кроме [[DONE]], заканчивается одним «?». Варианты в [[OPTIONS]] — это ответы, не вопросы. '
        'Приветствие только в начале.',
    ])


def transcript_text(doc):
    text = '\n'.join(('Интервьюер: ' if m.get('role') == 'assistant' else 'Сотрудник: ') + str(m.get('content', ''))
                     for m in doc.get('messages') or [])
    if len(text) > 32_000:  # влезть в контекст 16384: начало (роль) + конец (поправки)
        text = text[:6_000] + '\n…\n' + text[-26_000:]
    return text


def summary_prompt(doc, out_lang):
    lang_word = 'румынском (limba română)' if out_lang == 'ro' else 'русском'
    return '\n'.join([
        'Ниже — расшифровка интервью с сотрудником компании ' + COMPANY,
        'Сотрудник: отдел «%s», должность «%s», функции «%s» (roleKey=%s; roleKeys=%s).' % (
            DEPTS.get(doc.get('dept'), '—'), doc.get('position', ''), role_title(doc, 'ru'), role_key(doc), ','.join(role_keys(doc))),
        (doc.get('about') and 'Описание работы сотрудника: «' + doc['about'] + '». Извлечённые занятия: ' +
         json.dumps(doc.get('aboutAnalysis') or {}, ensure_ascii=False) + '.' or ''),
        'Составь структурированное резюме его рабочих процессов и требований к ERP. Все текстовые значения пиши на ' + lang_word + ' языке. '
        'Не выдумывай: если цифры или решения не названы, ставь null или пустой массив. Часы в неделю считай из названной частоты и длительности, только '
        'если обе названы. Поправки сотрудника к резюме (строки «Поправка к резюме» / «Corectare la rezumat») важнее более '
        'ранних ответов. Ответ сотрудника может быть выбранными вариантами через «;» и его уточнением после «—».',
        'Ответь только JSON-объектом такого вида:',
        '{"role_key":"' + role_key(doc) + '","role_keys":' + json.dumps(role_keys(doc), ensure_ascii=False) + ',"role_summary":"2–3 предложения о роли","responsibilities":["подтверждённые зоны ответственности"],'
        '"decision_rights":[{"decision":"решение","owner":"кто принимает","limit":"лимит или null","evidence":"основание и документ"}],'
        '"documents":[{"name":"документ","version":"версия или null","owner":"владелец","retention":"срок или null"}],'
        '"kpis":[{"name":"показатель","formula":"формула","source":"источник","frequency":"период","target":"цель или null"}],'
        '"exceptions":[{"event":"исключение","action":"действие","escalate_to":"кому эскалация"}],'
        '"erp_requirements":[{"requirement":"конкретное правило или функция","reason":"подтверждённая причина","priority":"high|medium|low","evidence":"пример и документ"}],'
        '"processes":[{"name":"короткое название процесса","description":"что '
        'делается и зачем, 1–2 предложения","frequency":"как часто, текстом","hours_per_week":число или null,"systems":'
        '["1С","Excel"],"inputs_from":["от кого или откуда данные"],"outputs_to":["кому передаётся результат"],"pain_points":'
        '["что идёт не так"],"judgement":"low|medium|high — насколько нужны опыт и решения человека","automation_potential":'
        'число 1–5,"automation_idea":"одно предложение, что можно упростить, или null"}],"handoffs":[{"with":"отдел или роль",'
        '"what":"что передаётся","issue":"проблема или null"}],"approvals":["согласования и подписи, сколько ждут"],'
        '"top_pains":["3–5 главных болей"],"keep_human":["что должно остаться за человеком"],"helper_wish":"что отдал бы '
        'помощнику, или null","open_questions":["что осталось непонятным"]}',
        '',
        'Расшифровка:',
        transcript_text(doc),
    ])


def analysis_prompt(n):
    return '\n'.join([
        'Ты — операционный консультант на фармацевтическом производстве. Компания: ' + COMPANY,
        'Ниже резюме интервью %d сотрудников (JSON; текст внутри может быть на русском или румынском). Сведи их в карту '
        'процессов компании и найди, что упростить в первую очередь.' % n,
        'Пиши по-русски. Не выдумывай цифры, которых нет в данных: часы суммируй только из названных. Учитывай, что ошибка '
        'в GMP-документах, сериях, деньгах и регистрационных данных дорого стоит — там риск выше.',
        'Ответь только JSON-объектом такого вида:',
        '{"headline":"главный вывод в 1–2 предложениях","automation_candidates":[{"rank":1,"task":"что автоматизировать",'
        '"who":["отделы"],"hours_per_week":сумма названных часов или null,"scores":{"time":1–5 сколько времени сэкономит,'
        '"rules":1–5 насколько работа по правилам,"data":1–5 насколько доступны входные данные,"risk":1–5 насколько опасна '
        'ошибка},"approach":"самый простой способ: шаблон, формула, правило в 1С или ERP, no-code, ИИ-помощник","human_check":'
        '"что проверяет человек","pilot":"план пилота на 2 недели"}],"process_catalog":[{"process":"название","departments":'
        '["отделы"],"people":число сотрудников,"hours_per_week":сумма названных часов или null,"systems":["системы"],"flow":'
        '"откуда → что делается → куда, одно предложение","issues":["проблемы"]}],"bottlenecks":[{"between":"отдел A ↔ '
        'отдел B","issue":"что не так","evidence":"какие роли об этом сказали"}],"keep_human":[{"task":"что","why":"почему"}],'
        '"duplicates":["одна и та же работа у разных людей или отделов"],"gaps":["каких отделов или ролей не хватает, что '
        'уточнить во втором раунде"]}',
        'automation_candidates — до 10, по убыванию пользы. process_catalog — объедини одинаковые процессы разных людей.',
    ])


def compact_summary(n, d):
    sm = d.get('summary') or {}
    procs = [{k: q.get(k) for k in ('name', 'frequency', 'hours_per_week', 'systems', 'inputs_from', 'outputs_to',
                                     'pain_points', 'automation_potential', 'automation_idea')}
             for q in (sm.get('processes') or []) if isinstance(q, dict)]
    return {'n': n, 'dept': DEPTS.get(d.get('dept'), '—'), 'position': d.get('position', ''),
            'role': sm.get('role_summary'), 'processes': procs, 'handoffs': sm.get('handoffs'),
            'top_pains': sm.get('top_pains'), 'keep_human': sm.get('keep_human')}


def pending_documents_note(items, announce):
    """Сотрудник не ждёт окончания долгого разбора: интервьюер знает, какие документы ещё разбираются или не прочитались."""
    pending = [prompt_safe(item.get('name') or 'Документ', 200) for item in items
               if item['status'] in ('queued', 'processing', 'analyzing')]
    failed = [prompt_safe(item.get('name') or 'Документ', 200) for item in items if item['status'] == 'failed']
    note = ''
    if pending:
        names = ', '.join('«%s»' % name for name in pending)
        if announce:
            note += ('\n[Документ ' + names + ' сейчас на стадии разбора, его содержание пока неизвестно. Начни ответ одной '
                     'короткой фразой на языке интервью: документ сейчас на стадии разбора, пусть сотрудник немного '
                     'подождёт — ты учтёшь его, как только разбор закончится. Затем продолжай интервью и не спрашивай '
                     'о содержании этого документа, пока нет его разбора.]')
        else:
            note += '\n[Документ ' + names + ' ещё на стадии разбора.]'
    if failed:
        note += '\n[Документ ' + ', '.join('«%s»' % name for name in failed) + ' не удалось прочитать автоматически'
        note += (': если он важен для ответа, попроси сотрудника кратко описать его словами.]' if announce else '.]')
    return note


def turn_messages(doc):
    msgs = [{'role': 'system', 'content': rules_prompt(doc)},
            {'role': 'user', 'content': 'Начни интервью: поздоровайся по имени, одним предложением объясни цель и задай первый вопрос.'}]
    hist = list(doc.get('messages') or [])[-12:]
    total = sum(len(str(m.get('content', ''))) for m in hist)
    while total > 12_000 and len(hist) > 4:
        total -= len(str(hist[0].get('content', '')))
        hist.pop(0)
    last_user = max((i for i, m in enumerate(hist) if m.get('role') != 'assistant'), default=-1)
    for position, m in enumerate(hist):
        c = str(m.get('content', ''))
        if m.get('role') == 'assistant':
            if m.get('questionKey'):
                c = '[[Q:%s]] %s' % (m['questionKey'], c)
            c = '[[%s]] %s' % (m.get('phase') or doc.get('phase') or 1, c)
            if m.get('options'):
                c += '\n[[OPTIONS %s: %s]]' % (m.get('mode') or 'many', ' | '.join(m['options']))
            msgs.append({'role': 'assistant', 'content': c})
        else:
            attachment_ids = m.get('attachmentIds') or []
            materials = [find_attachment(doc, aid) for aid in attachment_ids]
            names = [prompt_safe(a.get('name'), 200) for a in materials if a and a.get('name')]
            if names:
                c += '\n[К ответу приложены материалы: ' + ', '.join(names) + '.]'
            if attachment_ids:
                knowledge = knowledge_status(DB_PATH, doc['id'], attachment_ids)
                summaries = [prompt_safe(item['name'], 200)
                             + (' (' + prompt_safe(item['documentType'], 300) + ')' if item.get('documentType') else '')
                             + ': ' + prompt_safe(item['summary'], 2000) for item in knowledge['items']
                             if item['status'] in ('ready', 'extracted') and item.get('summary')]
                if summaries:
                    c += '\n[Разбор приложенных документов:\n' + '\n'.join(summaries) + ']'
                c += pending_documents_note(knowledge['items'], announce=position == last_user)
            msgs.append({'role': 'user', 'content': c})
    return msgs


# ---------- модель ----------

class LLMError(Exception):
    pass


_ai_cache = {'t': 0.0, 'ok': False}


def ai_available():
    if ANALYSIS_BASE and ANALYSIS_KEY:
        return True
    if time.time() - _ai_cache['t'] < 30:
        return _ai_cache['ok']
    ok = False
    try:
        with urllib.request.urlopen(OLLAMA + '/api/tags', timeout=3) as r:
            names = [m.get('name') for m in json.load(r).get('models', [])]
            ok = MODEL in names
    except Exception:
        ok = False
    _ai_cache.update(t=time.time(), ok=ok)
    return ok


def ollama_chat(messages, json_mode=False, temperature=0.4, timeout=300):
    body = {'model': MODEL, 'messages': messages, 'stream': False, 'think': False, 'keep_alive': '60m',
            'options': {'temperature': temperature, 'num_ctx': NUM_CTX}}
    if json_mode:
        body['format'] = 'json'
    req = urllib.request.Request(OLLAMA + '/api/chat', json.dumps(body).encode('utf-8'), {'Content-Type': 'application/json'})
    if not LLM_SEM.acquire(timeout=240):
        raise LLMError('busy')
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            content = json.load(r).get('message', {}).get('content', '')
    except Exception as e:  # сеть, таймаут, модель не загружена
        raise LLMError(str(e)[:200])
    finally:
        LLM_SEM.release()
    content = re.sub(r'<think>[\s\S]*?</think>', '', content).strip()
    if not content:
        raise LLMError('empty')
    return content


_warm = {'t': 0.0}


def warm_async():
    """Подгрузить модель заранее (пока сотрудник заполняет анкету), не чаще раза в минуту."""
    if ANALYSIS_BASE and ANALYSIS_KEY:
        return
    if time.time() - _warm['t'] < 60:
        return
    _warm['t'] = time.time()

    def run():
        try:
            body = json.dumps({'model': MODEL, 'prompt': '', 'keep_alive': '60m', 'options': {'num_ctx': NUM_CTX}}).encode()
            urllib.request.urlopen(urllib.request.Request(OLLAMA + '/api/generate', body, {'Content-Type': 'application/json'}),
                                   timeout=180).read()
        except Exception:
            pass
    threading.Thread(target=run, daemon=True).start()


def parse_json(text):
    try:
        return json.loads(text)
    except Exception:
        m = re.search(r'[\{\[][\s\S]*[\}\]]', text)
        if m:
            try:
                return json.loads(m.group(0))
            except Exception:
                pass
    raise LLMError('invalid_json')


# ---------- хранилище ----------

def db():
    con = sqlite3.connect(DB_PATH, timeout=10)
    con.row_factory = sqlite3.Row
    return con


def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    with DB_LOCK, db() as con:
        con.execute('PRAGMA journal_mode=WAL')
        con.execute('CREATE TABLE IF NOT EXISTS interviews (id TEXT PRIMARY KEY, token_hash TEXT UNIQUE NOT NULL, '
                    'doc TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)')
        con.execute('CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT NOT NULL)')
    init_knowledge(DB_PATH)


def token_hash(tok):
    return hashlib.sha256(tok.encode('utf-8')).hexdigest()


def load_by_token(tok):
    if not tok or len(tok) > 200:
        return None
    with DB_LOCK, db() as con:
        row = con.execute('SELECT id, doc FROM interviews WHERE token_hash=?', (token_hash(tok),)).fetchone()
    return (row['id'], json.loads(row['doc'])) if row else None


def load_by_id(iid):
    with DB_LOCK, db() as con:
        row = con.execute('SELECT doc FROM interviews WHERE id=?', (iid,)).fetchone()
    return json.loads(row['doc']) if row else None


def save_doc(iid, doc):
    doc['updatedAt'] = now_iso()
    raw = json.dumps(doc, ensure_ascii=False)
    with DB_LOCK, db() as con:
        con.execute('UPDATE interviews SET doc=?, updated_at=? WHERE id=?', (raw, doc['updatedAt'], iid))
    return doc


def attachments_root():
    return os.path.join(os.path.dirname(DB_PATH), 'attachments')


def attachment_path(iid, aid):
    if not re.fullmatch(r'[0-9a-f]{16}', iid or '') or not re.fullmatch(r'[0-9a-f]{24}', aid or ''):
        raise BadRequest('attachment')
    return os.path.join(attachments_root(), iid, aid)


def find_attachment(doc, aid):
    for item in doc.get('attachments') or []:
        if item.get('id') == aid:
            return item
    return None


def question_for_attachment(doc, question):
    messages = doc.get('messages') or []
    if not isinstance(question, int) or isinstance(question, bool) or question < 0 or question >= len(messages):
        raise BadRequest('question')
    item = messages[question]
    if item.get('role') != 'assistant':
        raise BadRequest('question')
    if sum(1 for a in doc.get('attachments') or [] if a.get('questionIndex') == question) >= MAX_FILES_PER_QUESTION:
        raise BadRequest('too_many_attachments')
    if len(doc.get('attachments') or []) >= MAX_ATTACHMENTS_PER_INTERVIEW:
        raise BadRequest('too_many_attachments')
    return item


def upload_path(iid, uid):
    if not re.fullmatch(r'[0-9a-f]{16}', iid or '') or not re.fullmatch(r'[0-9a-f]{32}', uid or ''):
        raise BadRequest('upload')
    return os.path.join(attachments_root(), '.uploads', iid, uid + '.part')


def remove_interview_attachments(iid):
    for folder in (os.path.join(attachments_root(), iid), os.path.join(attachments_root(), '.uploads', iid)):
        if os.path.isdir(folder):
            shutil.rmtree(folder)


def kv_get(key):
    with DB_LOCK, db() as con:
        row = con.execute('SELECT value FROM kv WHERE key=?', (key,)).fetchone()
    return json.loads(row['value']) if row else None


def kv_set(key, value):
    with DB_LOCK, db() as con:
        con.execute('INSERT INTO kv(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',
                    (key, json.dumps(value, ensure_ascii=False)))


# ---------- проверка данных ----------

class BadRequest(Exception):
    pass


def s(v, n):
    return '' if v is None else str(v)[:n]


def str_list(v, n_items, n_len):
    if not isinstance(v, list):
        return []
    return [s(x, n_len) for x in v[:n_items] if isinstance(x, (str, int, float)) and str(x).strip()]


def clean_messages(msgs):
    if not isinstance(msgs, list):
        raise BadRequest('messages')
    out = []
    for m in msgs[:400]:
        if not isinstance(m, dict) or m.get('role') not in ('user', 'assistant'):
            continue
        item = {'role': m['role'], 'content': s(m.get('content'), 6000), 't': s(m.get('t'), 40)}
        if isinstance(m.get('phase'), int) and 1 <= m['phase'] <= 5:
            item['phase'] = m['phase']
        question_key = s(m.get('questionKey'), 40)
        if re.fullmatch(r'[A-Za-z0-9-]{1,32}', question_key):
            item['questionKey'] = question_key
        if m['role'] == 'assistant':
            opts = str_list(m.get('options'), 12, 120)
            if opts:
                item['options'] = opts
                item['mode'] = 'one' if m.get('mode') == 'one' else 'many'
        else:
            picked = str_list(m.get('picked'), 14, 120)
            if picked:
                item['picked'] = picked
                item['own'] = s(m.get('own'), 6000)
            attachment_ids = str_list(m.get('attachmentIds'), MAX_FILES_PER_QUESTION, 24)
            if attachment_ids:
                item['attachmentIds'] = attachment_ids
        out.append(item)
    return out


def clean_doc(new, old):
    """Респондент меняет только содержимое своего интервью; служебные поля — с сервера."""
    if not isinstance(new, dict):
        raise BadRequest('doc')
    d = dict(old)
    for k, n in (('name', 80), ('position', 120)):
        if k in new:
            d[k] = s(new[k], n).strip()
    if new.get('dept') in DEPTS:
        d['dept'] = new['dept']
    if isinstance(new.get('roleKeys'), list):
        selected = []
        for key in new['roleKeys']:
            if key in ROLE_PACKS and key not in selected:
                selected.append(key)
        if selected:
            d['roleKeys'] = selected
            d['roleKey'] = selected[0]
    elif new.get('roleKey') in ROLE_PACKS:
        d['roleKey'] = new['roleKey']
        d['roleKeys'] = [new['roleKey']] + [key for key in role_keys(d) if key != new['roleKey']]
    else:
        d['roleKeys'] = role_keys(d)
        d['roleKey'] = role_keys(d)[0]
    d['about'] = old.get('about', '')
    d['aboutAnalysis'] = old.get('aboutAnalysis') or analyze_about('')
    if new.get('lang') in ('ru', 'ro'):
        d['lang'] = new['lang']
    if new.get('status') in STATUSES:
        d['status'] = new['status']
    if new.get('mode') in ('ai', 'script'):
        d['mode'] = new['mode']
    if isinstance(new.get('phase'), int) and 1 <= new['phase'] <= 5:
        d['phase'] = new['phase']
    d['attachments'] = list(old.get('attachments') or [])
    if 'messages' in new:
        d['messages'] = clean_messages(new['messages'])
        for index, message in enumerate(d['messages']):
            if message.get('role') != 'user':
                continue
            valid = []
            for aid in message.get('attachmentIds') or []:
                item = find_attachment(d, aid)
                if (item and index > 0 and d['messages'][index - 1].get('role') == 'assistant'
                        and item.get('questionIndex') == index - 1):
                    valid.append(aid)
                    item['messageIndex'] = index
            if valid:
                message['attachmentIds'] = valid
            else:
                message.pop('attachmentIds', None)
    if isinstance(new.get('script'), dict):
        sc = new['script']
        d['script'] = {'stage': s(sc.get('stage'), 10), 'i': int(sc.get('i') or 0) if str(sc.get('i') or 0).isdigit() else 0,
                       'task': int(sc.get('task') or 1) if str(sc.get('task') or 1).isdigit() else 1}
    if 'summary' in new:
        if new['summary'] is None or isinstance(new['summary'], dict):
            d['summary'] = new['summary']
    for k in ('summaryBy', 'summaryAt', 'finishedAt', 'submittedAt', 'startedAt'):
        if k in new:
            d[k] = s(new[k], 40)
    if len(json.dumps(d, ensure_ascii=False)) > MAX_DOC:
        raise BadRequest('too_large')
    return d


# ---------- ограничения частоты ----------

_hits = {}
_hits_lock = threading.Lock()


def limited(key, limit, window):
    t = time.time()
    with _hits_lock:
        arr = [x for x in _hits.get(key, []) if t - x < window]
        if len(arr) >= limit:
            _hits[key] = arr
            return True
        arr.append(t)
        _hits[key] = arr
        return False


def admin_password():
    try:
        with open(ADMIN_FILE, encoding='utf-8') as f:
            return f.read().strip()
    except OSError:
        return ''


def public_url():
    try:
        with open(TUNNEL_LOG, encoding='utf-8', errors='ignore') as f:
            found = re.findall(r'https://[a-z0-9-]+\.trycloudflare\.com', f.read())
        return found[-1] if found else ''
    except OSError:
        return ''


# ---------- HTTP ----------

SEC_HEADERS = {
    'X-Content-Type-Options': 'nosniff',
    'Referrer-Policy': 'no-referrer',
    'Content-Security-Policy': ("default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline' "
                                "https://fonts.googleapis.com; font-src https://fonts.gstatic.com; img-src 'self' data:; "
                                "media-src 'self' blob:; connect-src 'self'; frame-ancestors 'self' " + STABLE_ORIGIN + "; base-uri 'none'; form-action 'self'"),
}


class Handler(BaseHTTPRequestHandler):
    server_version = 'ProcessSurvey/1'
    sys_version = ''

    def log_message(self, fmt, *args):  # без тел и токенов: метод, путь, код
        pass

    def client_ip(self):
        return (self.headers.get('CF-Connecting-IP') or self.headers.get('X-Forwarded-For', '').split(',')[0].strip()
                or self.client_address[0])

    def send_json(self, code, obj):
        raw = json.dumps(obj, ensure_ascii=False).encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Cache-Control', 'no-store')
        for k, v in SEC_HEADERS.items():
            self.send_header(k, v)
        self.send_header('Content-Length', str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def send_healthz(self):  # постоянная страница проверяет, жив ли текущий адрес
        raw = b'{"ok": true}'
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Access-Control-Allow-Origin', STABLE_ORIGIN)
        self.send_header('Content-Length', str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def err(self, code, name):
        self.send_json(code, {'error': name})

    def body(self):
        n = int(self.headers.get('Content-Length') or 0)
        if n > MAX_BODY:
            raise BadRequest('too_large')
        raw = self.rfile.read(n) if n else b'{}'
        try:
            return json.loads(raw.decode('utf-8') or '{}')
        except Exception:
            raise BadRequest('json')

    def file_body(self, limit=UPLOAD_CHUNK):
        try:
            n = int(self.headers.get('Content-Length') or 0)
        except ValueError:
            raise BadRequest('content_length')
        if n <= 0:
            raise BadRequest('empty_file')
        if n > limit:
            self.close_connection = True
            raise BadRequest('chunk_too_large' if limit == UPLOAD_CHUNK else 'file_too_large')
        raw = self.rfile.read(n)
        if len(raw) != n:
            raise BadRequest('incomplete_file')
        return raw

    def bearer(self):
        h = self.headers.get('Authorization', '')
        return h[7:].strip() if h.startswith('Bearer ') else ''

    def admin_guard(self):
        ip = self.client_ip()
        fails = [x for x in _hits.get('adminfail:' + ip, []) if time.time() - x < 900]
        if len(fails) >= 10:
            self.err(429, 'too_many_attempts')
            return False
        key = self.headers.get('X-Admin-Key', '')
        pw = admin_password()
        if pw and hmac.compare_digest(key.encode('utf-8'), pw.encode('utf-8')):
            return True
        with _hits_lock:
            _hits.setdefault('adminfail:' + ip, []).append(time.time())
        self.err(401, 'unauthorized')
        return False

    # --- статика ---
    def serve_index(self):
        try:
            with open(INDEX_HTML, 'rb') as f:
                raw = f.read()
        except OSError:
            return self.err(500, 'no_index')
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Cache-Control', 'no-cache')
        for k, v in SEC_HEADERS.items():
            self.send_header(k, v)
        self.send_header('Content-Length', str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def send_attachment(self, iid, item):
        if not item or item.get('kind') != 'file':
            return self.err(404, 'not_found')
        path = attachment_path(iid, item.get('id'))
        try:
            size = os.path.getsize(path)
            stream = open(path, 'rb')
        except OSError:
            return self.err(404, 'not_found')
        with stream:
            self.send_response(200)
            self.send_header('Content-Type', item.get('mime') or 'application/octet-stream')
            self.send_header('Cache-Control', 'no-store')
            self.send_header('Content-Disposition', "attachment; filename*=UTF-8''" + quote(item.get('name') or 'attachment', safe=''))
            for k, v in SEC_HEADERS.items():
                self.send_header(k, v)
            self.send_header('Content-Length', str(size))
            self.end_headers()
            shutil.copyfileobj(stream, self.wfile, length=1024 * 1024)

    def send_voice(self, key):
        path = voice_audio_path(key)
        if path is None:
            return self.err(404, 'not_found')
        try:
            size = path.stat().st_size
            stream = path.open('rb')
        except OSError:
            return self.err(404, 'not_found')
        with stream:
            self.send_response(200)
            self.send_header('Content-Type', 'audio/mp4')
            self.send_header('Cache-Control', 'no-store')
            for k, v in SEC_HEADERS.items():
                self.send_header(k, v)
            self.send_header('Content-Length', str(size))
            self.end_headers()
            shutil.copyfileobj(stream, self.wfile, length=1024 * 1024)

    def do_GET(self):
        self.route('GET')

    def do_POST(self):
        self.route('POST')

    def do_PUT(self):
        self.route('PUT')

    def do_DELETE(self):
        self.route('DELETE')

    def route(self, method):
        path = urlparse(self.path).path
        try:
            if method == 'GET' and path in ('/', '/admin', '/index.html'):
                return self.serve_index()
            if method == 'GET' and path == '/healthz':
                return self.send_healthz()
            if method == 'GET' and path == '/api/config':
                ai = ai_available()
                if ai:
                    warm_async()
                return self.send_json(200, {'ai': ai, 'model': ANALYSIS_MODEL if ANALYSIS_BASE and ANALYSIS_KEY else MODEL,
                                            'stableUrl': stable_url(), 'stableOrigin': STABLE_ORIGIN,
                                            'ownerVoice': voice_available()})
            if path == '/api/welcome-voice' and method == 'GET':
                return self.welcome_voice()
            if path == '/api/interviews' and method == 'POST':
                return self.create_interview()
            if path == '/api/me':
                if method == 'GET':
                    return self.get_me()
                if method == 'PUT':
                    return self.put_me()
            if path == '/api/me/voice-prefetch' and method == 'POST':
                return self.me_voice_prefetch()
            match = re.fullmatch(r'/api/me/voice/(\d{1,3})', path)
            if match and method == 'GET':
                return self.me_voice(int(match.group(1)))
            if path == '/api/me/attachments/analyze' and method == 'POST':
                return self.me_analyze_attachments()
            if path == '/api/me/attachments' and method == 'POST':
                return self.upload_attachment()
            if path == '/api/me/attachments/chunk' and method == 'POST':
                return self.upload_attachment_chunk()
            if path == '/api/me/attachments/complete' and method == 'POST':
                return self.complete_attachment_upload()
            if path == '/api/me/attachment-links' and method == 'POST':
                return self.create_attachment_link()
            match = re.fullmatch(r'/api/me/attachments/([0-9a-f]{24})', path)
            if match and method in ('GET', 'DELETE'):
                return self.me_attachment(match.group(1), delete=method == 'DELETE')
            if path == '/api/me/turn' and method == 'POST':
                return self.me_turn()
            if path == '/api/me/summary' and method == 'POST':
                return self.me_summary()
            if path.startswith('/api/admin/'):
                return self.admin(method, path[len('/api/admin/'):])
            return self.err(404, 'not_found')
        except BadRequest as e:
            return self.err(400, str(e) or 'bad_request')
        except LLMError as e:
            code = 503
            return self.send_json(code, {'error': 'ai_unavailable' if str(e) != 'invalid_json' else 'invalid_json'})
        except Exception:
            return self.err(500, 'server_error')

    # --- респондент ---
    def create_interview(self):
        if limited('create:' + self.client_ip(), 30, 3600):
            return self.err(429, 'rate_limited')
        b = self.body()
        name, pos = s(b.get('name'), 80).strip(), s(b.get('position'), 120).strip()
        selected_role = s(b.get('roleKey'), 2)
        selected_roles = []
        if isinstance(b.get('roleKeys'), list):
            for key in b['roleKeys']:
                if not isinstance(key, str) or key not in ROLE_PACKS:
                    raise BadRequest('fields')
                if key not in selected_roles:
                    selected_roles.append(key)
        if selected_role and selected_role not in ROLE_PACKS:
            raise BadRequest('fields')
        if selected_role and selected_role not in selected_roles:
            selected_roles.insert(0, selected_role)
        if not selected_roles:
            selected_roles = [role_key({'dept': b.get('dept')})]
        selected_role = selected_roles[0]
        if not name or not pos or b.get('dept') not in DEPTS or b.get('lang') not in ('ru', 'ro') or b.get('consent') is not True:
            raise BadRequest('fields')
        about = s(b.get('about'), 4000).strip()
        # Никакого отдельного запроса к модели на старте: смысл уточняется внутри самого интервью.
        about_analysis = analyze_about(about)
        warm_async()
        iid = secrets.token_hex(8)
        tok = secrets.token_urlsafe(32)
        t = now_iso()
        doc = {'id': iid, 'name': name, 'dept': b['dept'], 'position': pos, 'lang': b['lang'], 'consent': True,
               'roleKey': selected_role, 'roleKeys': selected_roles, 'about': about, 'aboutAnalysis': about_analysis,
               'status': 'in_progress', 'mode': 'ai' if (b.get('mode') == 'ai' and ai_available()) else 'script',
               'phase': 1, 'messages': [], 'attachments': [], 'script': {'stage': 'role', 'i': 0, 'task': 1}, 'summary': None,
               'startedAt': t, 'updatedAt': t, 'createdAt': t}
        with DB_LOCK, db() as con:
            con.execute('INSERT INTO interviews(id, token_hash, doc, created_at, updated_at) VALUES(?,?,?,?,?)',
                        (iid, token_hash(tok), json.dumps(doc, ensure_ascii=False), t, t))
        return self.send_json(200, {'token': tok, 'doc': doc})

    def me(self):
        found = load_by_token(self.bearer())
        if not found:
            self.err(404, 'not_found')
        return found

    def get_me(self):
        found = self.me()
        if found:
            self.send_json(200, {'doc': found[1]})

    def put_me(self):
        if limited('put:' + self.client_ip(), 600, 3600):
            return self.err(429, 'rate_limited')
        found = self.me()
        if not found:
            return
        iid, old = found
        doc = clean_doc(self.body().get('doc'), old)
        doc = save_doc(iid, doc)
        sync_knowledge(DB_PATH, doc)
        self.send_json(200, {'ok': True, 'updatedAt': doc['updatedAt']})

    def checked_upload(self, doc, data):
        name = os.path.basename(s(data.get('name'), 240).replace('\\', '/')).strip()
        name = re.sub(r'[\x00-\x1f\x7f]', '_', name)
        ext = os.path.splitext(name)[1].lower()
        if not name or ext not in FILE_TYPES:
            raise BadRequest('unsupported_file_type')
        try:
            size = int(data.get('size'))
            question = int(data.get('question'))
        except (TypeError, ValueError):
            raise BadRequest('upload')
        if size <= 0:
            raise BadRequest('empty_file')
        if size > MAX_FILE:
            raise BadRequest('file_too_large')
        question_for_attachment(doc, question)
        uid = s(data.get('upload'), 32)
        if not re.fullmatch(r'[0-9a-f]{32}', uid):
            raise BadRequest('upload')
        return name, size, question, uid

    def finish_upload(self, iid, doc, question, name, part, size):
        if not os.path.isfile(part) or os.path.getsize(part) != size:
            raise BadRequest('incomplete_file')
        question_for_attachment(doc, question)
        used = sum(int(a.get('size') or 0) for a in doc.get('attachments') or [] if a.get('kind') == 'file')
        if used + size > MAX_ATTACHMENT_BYTES_PER_INTERVIEW:
            raise BadRequest('attachment_quota')
        digest = hashlib.sha256()
        with open(part, 'rb') as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b''):
                digest.update(block)
        aid = secrets.token_hex(12)
        final = attachment_path(iid, aid)
        os.makedirs(os.path.dirname(final), mode=0o700, exist_ok=True)
        os.replace(part, final)
        item = {'id': aid, 'kind': 'file', 'name': name, 'mime': FILE_TYPES[os.path.splitext(name)[1].lower()],
                'size': size, 'sha256': digest.hexdigest(), 'questionIndex': question,
                'question': s((doc.get('messages') or [])[question].get('content'), 1000), 'createdAt': now_iso()}
        doc.setdefault('attachments', []).append(item)
        try:
            save_doc(iid, doc)
        except Exception:
            try:
                os.unlink(final)
            except OSError:
                pass
            doc['attachments'].pop()
            raise
        enqueue_knowledge(DB_PATH, doc, item)
        return item

    def upload_attachment(self):
        if limited('upload:' + self.client_ip(), 5000, 3600):
            return self.err(429, 'rate_limited')
        found = self.me()
        if not found:
            return
        iid, doc = found
        query = {k: v[-1] for k, v in parse_qs(urlparse(self.path).query).items()}
        query['size'] = self.headers.get('Content-Length')
        query['upload'] = secrets.token_hex(16)
        name, size, question, uid = self.checked_upload(doc, query)
        raw = self.file_body()
        if len(raw) != size:
            raise BadRequest('incomplete_file')
        part = upload_path(iid, uid)
        os.makedirs(os.path.dirname(part), mode=0o700, exist_ok=True)
        with open(part, 'xb') as stream:
            stream.write(raw)
        item = self.finish_upload(iid, doc, question, name, part, size)
        self.send_json(200, {'attachment': item})

    def upload_attachment_chunk(self):
        if limited('upload:' + self.client_ip(), 5000, 3600):
            return self.err(429, 'rate_limited')
        found = self.me()
        if not found:
            return
        iid, doc = found
        query = {k: v[-1] for k, v in parse_qs(urlparse(self.path).query).items()}
        name, size, question, uid = self.checked_upload(doc, query)
        try:
            offset = int(query.get('offset'))
        except (TypeError, ValueError):
            raise BadRequest('offset')
        raw = self.file_body()
        if offset < 0 or offset + len(raw) > size:
            raise BadRequest('offset')
        part = upload_path(iid, uid)
        if offset and (not os.path.isfile(part) or os.path.getsize(part) < offset):
            raise BadRequest('offset')
        os.makedirs(os.path.dirname(part), mode=0o700, exist_ok=True)
        with open(part, 'r+b' if os.path.exists(part) else 'wb') as stream:
            stream.seek(offset)
            stream.write(raw)
        self.send_json(200, {'ok': True, 'received': offset + len(raw), 'total': size})

    def complete_attachment_upload(self):
        found = self.me()
        if not found:
            return
        iid, doc = found
        name, size, question, uid = self.checked_upload(doc, self.body())
        item = self.finish_upload(iid, doc, question, name, upload_path(iid, uid), size)
        self.send_json(200, {'attachment': item})

    def me_analyze_attachments(self):
        found = self.me()
        if not found:
            return
        iid, doc = found
        body = self.body()
        ids = body.get('ids')
        if not isinstance(ids, list) or not ids or len(ids) > MAX_FILES_PER_QUESTION:
            raise BadRequest('attachments')
        items = []
        for aid in ids:
            if not isinstance(aid, str) or not re.fullmatch(r'[0-9a-f]{24}', aid):
                raise BadRequest('attachments')
            item = find_attachment(doc, aid)
            if not item:
                return self.err(404, 'not_found')
            items.append(item)
        for item in items:
            enqueue_knowledge(DB_PATH, doc, item)
        result = knowledge_status(DB_PATH, iid, ids)
        return self.send_json(200 if result['done'] else 202, result)

    def create_attachment_link(self):
        found = self.me()
        if not found:
            return
        iid, doc = found
        b = self.body()
        try:
            question = int(b.get('question'))
        except (TypeError, ValueError):
            raise BadRequest('question')
        url = s(b.get('url'), 2000).strip()
        parsed = urlparse(url)
        if (parsed.scheme != 'https' or parsed.hostname != 'docs.google.com'
                or not parsed.path.startswith('/spreadsheets/') or parsed.username or parsed.password):
            raise BadRequest('invalid_google_sheet_url')
        question_for_attachment(doc, question)
        item = {'id': secrets.token_hex(12), 'kind': 'link', 'name': 'Google Таблица', 'url': url,
                'mime': 'text/uri-list', 'size': 0, 'questionIndex': question,
                'question': s((doc.get('messages') or [])[question].get('content'), 1000), 'createdAt': now_iso()}
        doc.setdefault('attachments', []).append(item)
        save_doc(iid, doc)
        enqueue_knowledge(DB_PATH, doc, item)
        self.send_json(200, {'attachment': item})

    def me_attachment(self, aid, delete=False):
        found = self.me()
        if not found:
            return
        iid, doc = found
        item = find_attachment(doc, aid)
        if not item:
            return self.err(404, 'not_found')
        if not delete:
            return self.send_attachment(iid, item)
        if item.get('messageIndex') is not None:
            raise BadRequest('attachment_already_sent')
        doc['attachments'] = [a for a in doc.get('attachments') or [] if a.get('id') != aid]
        save_doc(iid, doc)
        with DB_LOCK, db() as con:
            con.execute('DELETE FROM knowledge_documents WHERE attachment_id=?', (aid,))
        if item.get('kind') == 'file':
            try:
                os.unlink(attachment_path(iid, aid))
            except FileNotFoundError:
                pass
        self.send_json(200, {'ok': True})

    def welcome_voice(self):
        if limited('welcome-voice:' + self.client_ip(), 240, 3600):
            return self.err(429, 'rate_limited')
        if not voice_available():
            return self.err(503, 'owner_voice_unavailable')
        query = parse_qs(urlparse(self.path).query)
        lang = query.get('lang', ['ru'])[0]
        if lang not in WELCOME_VOICE:
            raise BadRequest('lang')
        status, key = request_voice(WELCOME_VOICE[lang], lang)
        if status == 'ready':
            return self.send_voice(key)
        if status == 'failed':
            return self.err(503, 'owner_voice_failed')
        return self.send_json(202, {'status': 'working', 'retryAfter': 2})

    def me_voice_prefetch(self):
        found = self.me()
        if not found:
            return
        iid, doc = found
        if limited('voice-prefetch:' + iid, 240, 3600):
            return self.err(429, 'rate_limited')
        if not voice_available():
            return self.err(503, 'owner_voice_unavailable')
        body = self.body()
        index = body.get('message')
        count = body.get('count', 2)
        if isinstance(index, bool) or not isinstance(index, int):
            raise BadRequest('question')
        if isinstance(count, bool) or not isinstance(count, int):
            raise BadRequest('count')
        count = max(0, min(2, count))
        messages = doc.get('messages') or []
        if index < 0 or index >= len(messages) or messages[index].get('role') != 'assistant':
            return self.err(404, 'not_found')
        text = messages[index].get('content') or ''
        if not text.strip() or len(text) > 4000:
            raise BadRequest('voice_text')
        lang = doc.get('lang') if doc.get('lang') in ('ru', 'ro') else 'ru'
        texts = [text]
        script = doc.get('script') or {}
        if index == len(messages) - 1 and doc.get('mode') == 'script' and script.get('stage') == 'role':
            questions = prioritize_questions(role_questions(doc, lang), doc.get('aboutAnalysis'))
            current = script.get('i') if isinstance(script.get('i'), int) else 0
            texts.extend(item['text'] for item in questions[current + 1:current + 1 + count])
        statuses = [request_voice(item, lang)[0] for item in texts]
        working = 'working' in statuses
        return self.send_json(202 if working else 200, {
            'status': 'working' if working else 'ready', 'queued': len(statuses),
            'ready': statuses.count('ready'), 'failed': statuses.count('failed'),
        })

    def me_voice(self, index):
        found = self.me()
        if not found:
            return
        iid, doc = found
        if limited('voice:' + iid, 5000, 3600):
            return self.err(429, 'rate_limited')
        if not voice_available():
            return self.err(503, 'owner_voice_unavailable')
        messages = doc.get('messages') or []
        if index < 0 or index >= len(messages) or messages[index].get('role') != 'assistant':
            return self.err(404, 'not_found')
        text = messages[index].get('content') or ''
        if not text.strip() or len(text) > 4000:
            raise BadRequest('voice_text')
        status, key = request_voice(text, doc.get('lang') if doc.get('lang') in ('ru', 'ro') else 'ru')
        if status == 'ready':
            return self.send_voice(key)
        if status == 'failed':
            return self.err(503, 'owner_voice_failed')
        return self.send_json(202, {'status': 'working', 'retryAfter': 2})

    def me_turn(self):
        if limited('turn:' + self.client_ip(), 240, 3600):
            return self.err(429, 'rate_limited')
        found = self.me()
        if not found:
            return
        _, doc = found
        msgs = doc.get('messages') or []
        if msgs and msgs[-1].get('role') != 'user':
            return self.err(409, 'not_your_turn')
        if sum(1 for m in msgs if m.get('role') == 'assistant') >= MAX_TURNS:
            return self.err(429, 'too_many_turns')
        if not ai_available():
            raise LLMError('down')
        text = assistant_chat(turn_messages(doc), temperature=0.25, timeout=60, max_tokens=700, reasoning_effort='low')
        self.send_json(200, {'text': text})

    def me_summary(self):
        if limited('sum:' + self.client_ip(), 40, 3600):
            return self.err(429, 'rate_limited')
        found = self.me()
        if not found:
            return
        _, doc = found
        if sum(1 for m in doc.get('messages') or [] if m.get('role') == 'user') < 2:
            raise BadRequest('too_short')
        if not ai_available():
            raise LLMError('down')
        text = assistant_chat([{'role': 'user', 'content': summary_prompt(doc, doc.get('lang', 'ru'))}],
                           json_mode=True, temperature=0.2, timeout=300)
        self.send_json(200, {'summary': parse_json(text)})

    # --- руководитель ---
    def admin(self, method, sub):
        if not self.admin_guard():
            return
        if method == 'GET' and sub == 'ping':
            return self.send_json(200, {'ok': True, 'publicUrl': public_url(), 'stableUrl': stable_url(), 'ai': ai_available(),
                                        'model': ANALYSIS_MODEL if ANALYSIS_BASE and ANALYSIS_KEY else MODEL})
        if method == 'GET' and sub == 'interviews':
            with DB_LOCK, db() as con:
                rows = con.execute('SELECT doc FROM interviews ORDER BY updated_at DESC').fetchall()
            return self.send_json(200, {'interviews': [json.loads(r['doc']) for r in rows], 'publicUrl': public_url(), 'stableUrl': stable_url()})
        if method == 'GET' and sub == 'knowledge':
            query = parse_qs(urlparse(self.path).query)
            try:
                limit = int(query.get('limit', ['100'])[0])
            except ValueError:
                limit = 100
            items = list_knowledge(DB_PATH, query.get('q', [''])[0][:200], limit)
            return self.send_json(200, {'items': items, 'total': len(items)})
        match_attachment = re.fullmatch(r'attachments/([0-9a-f]{24})', sub)
        if method == 'GET' and match_attachment:
            with DB_LOCK, db() as con:
                rows = con.execute('SELECT id, doc FROM interviews').fetchall()
            for row in rows:
                doc = json.loads(row['doc'])
                item = find_attachment(doc, match_attachment.group(1))
                if item:
                    return self.send_attachment(row['id'], item)
            return self.err(404, 'not_found')
        m = re.fullmatch(r'interviews/([0-9a-f]{16})(/summary|/extract|/resume-link)?', sub)
        if m:
            iid, tail = m.group(1), m.group(2)
            doc = load_by_id(iid)
            if not doc:
                return self.err(404, 'not_found')
            if method == 'DELETE' and not tail:
                with DB_LOCK, db() as con:
                    con.execute('DELETE FROM interviews WHERE id=?', (iid,))
                delete_knowledge(DB_PATH, iid)
                remove_interview_attachments(iid)
                return self.send_json(200, {'ok': True})
            if method == 'POST' and tail == '/resume-link':
                # новая ссылка для продолжения: ключ меняется, прежний (у сотрудника) перестаёт работать;
                # исходный ключ не восстановить — в БД только его sha256
                tok = secrets.token_urlsafe(32)
                with DB_LOCK, db() as con:
                    con.execute('UPDATE interviews SET token_hash=? WHERE id=?', (token_hash(tok), iid))
                base = stable_url() or (public_url() + '/')
                return self.send_json(200, {'url': base + '#t=' + tok})
            if method == 'POST' and tail == '/extract':
                if not ai_available():
                    raise LLMError('down')
                text = assistant_chat([{'role': 'user', 'content': summary_prompt(doc, 'ru')}],
                                   json_mode=True, temperature=0.2, timeout=300)
                return self.send_json(200, {'summary': parse_json(text)})
            if method == 'PUT' and tail == '/summary':
                summ = self.body().get('summary')
                if not isinstance(summ, dict):
                    raise BadRequest('summary')
                doc['summary'] = summ
                doc['summaryBy'] = 'owner'
                doc['summaryAt'] = now_iso()
                if len(json.dumps(doc, ensure_ascii=False)) > MAX_DOC:
                    raise BadRequest('too_large')
                return self.send_json(200, {'doc': save_doc(iid, doc)})
        if sub == 'analysis':
            if method == 'GET':
                return self.send_json(200, {'analysis': kv_get('analysis')})
            if method == 'PUT':
                a = self.body().get('analysis')
                if not isinstance(a, dict):
                    raise BadRequest('analysis')
                kv_set('analysis', a)
                return self.send_json(200, {'ok': True})
        if sub == 'analysis/run' and method == 'POST':
            with DB_LOCK, db() as con:
                rows = con.execute('SELECT doc FROM interviews').fetchall()
            docs = [json.loads(r['doc']) for r in rows]
            items = [d for d in docs if d.get('summary')]
            if not items:
                raise BadRequest('no_summaries')
            if not ai_available():
                raise LLMError('down')
            payload = [compact_summary(i + 1, d) for i, d in enumerate(items)]
            chunks, cur = [], []
            for p in payload:
                cur.append(p)
                if len(json.dumps(cur, ensure_ascii=False)) > ANALYSIS_CHUNK and len(cur) > 1:
                    chunks.append(cur[:-1])
                    cur = [p]
            chunks.append(cur)
            parts = []
            for ch in chunks:
                txt = json.dumps(ch, ensure_ascii=False)[:ANALYSIS_CHUNK + 4000]
                parts.append(parse_json(assistant_chat([{'role': 'user', 'content': analysis_prompt(len(ch)) + '\n\nРезюме интервью:\n' + txt}],
                                                    json_mode=True, temperature=0.2, timeout=600)))
            if len(parts) == 1:
                return self.send_json(200, {'analysis': parts[0], 'basedOn': len(items)})
            merged = json.dumps(parts, ensure_ascii=False)[:ANALYSIS_CHUNK + 8000]
            text = assistant_chat([{'role': 'user', 'content': analysis_prompt(len(items)) + '\n\nНиже не резюме, а частичные анализы '
                                 'по группам сотрудников в том же формате. Сведи их в один анализ: объедини одинаковые процессы и '
                                 'кандидатов, сложи часы, пересчитай ранги.\n\n' + merged}],
                               json_mode=True, temperature=0.2, timeout=600)
            return self.send_json(200, {'analysis': parse_json(text), 'basedOn': len(items)})
        return self.err(404, 'not_found')


def main():
    init_db()
    start_knowledge_worker()
    if not admin_password():
        os.makedirs(BASE, exist_ok=True)
        with open(ADMIN_FILE, 'w', encoding='utf-8') as f:
            f.write(secrets.token_urlsafe(12) + '\n')
        os.chmod(ADMIN_FILE, 0o600)
    srv = ThreadingHTTPServer(('127.0.0.1', PORT), Handler)
    srv.daemon_threads = True
    print('process-survey on 127.0.0.1:%d, model %s' % (PORT, MODEL), flush=True)
    srv.serve_forever()


if __name__ == '__main__':
    main()

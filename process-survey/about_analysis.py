#!/usr/bin/env python3
"""Извлечение занятий из свободного описания работы без домысливания."""
import json
import re

STOP = set('и в во на с по за от до из у о но а как что это этот эта эти для при или их им его её ее мы вы он она они мой моя мои ваш ваши ваша наш наша нас вам вас нам вами вас не неё нет да есть быть был были была было будет сам сама само самые самый очень более менее также тоже только уже ещё еще когда где кто чем кем чего если надо нужно можно нельзя все всех всё всю всем весь вся весьма очень много мало обычно обычный каждый каждая каждые каждое каждым each and the a an de la din cu în pe pentru că este sunt suntem sunteți sunteţi sunteti este sunt sunteţi sunteți această aceasta aceste acești acest acesta acesti acestia al ale au ai am avea avem aveți aveti aveţi face fac facem faceți faceti faceti facut facă făcând ca sa să şi și ți ţi un o unul oarecare care cine ce cea ceea ceeace'.split())

ACTIVITY_RULES = {
    'planning': ('Планирование', ['планирован', 'план', 'график', 'planific', 'program']),
    'reporting': ('Отчёты и сводки', ['отчет', 'отчёт', 'свод', 'raport', 'report', 'centraliz']),
    'reconciliation': ('Сверки и согласование данных', ['сверк', 'сверя', 'согласован', 'reconcil', 'reconcilier']),
    'data_entry': ('Ввод и перенос данных', ['ввод', 'перенос', 'загруз', 'introduc', 'import']),
    'production': ('Производственные операции', ['производств', 'партия', 'серия', 'операция', 'produc', 'lot']),
    'quality': ('Контроль качества', ['качеств', 'calitat', 'контрол']),
    'documents': ('Документы и инструкции', ['документ', 'инструкц', 'регламент', 'журнал', 'document', 'procedur']),
    'procurement': ('Закупки и поставщики', ['закуп', 'поставщик', 'achizi', 'furnizor']),
    'warehouse': ('Склад и остатки', ['склад', 'остат', 'stoc', 'depozit']),
    'sales': ('Продажи и заказы', ['продаж', 'заказ', 'vânz', 'comand']),
    'clients': ('Работа с клиентами', ['клиент', 'client']),
    'analysis': ('Анализ и аналитика', ['анализ', 'analiz']),
    'approvals': ('Согласования и подписи', ['соглас', 'утвержд', 'подпис', 'aprob', 'semn']),
    'training': ('Обучение и допуски', ['обуч', 'instr', 'training', 'calific']),
    'inventory': ('Инвентаризация', ['инвентар', 'inventar']),
    'shipping': ('Отгрузка и доставка', ['отгруз', 'достав', 'livr', 'exped']),
    'validation': ('Валидация и квалификация', ['валидац', 'квалификац', 'valid', 'calific']),
    'regulatory': ('Регистрация и регуляторика', ['регистрац', 'досье', 'вариаци', 'reglement', 'înregistr']),
    'packaging': ('Упаковка и печать', ['упаков', 'печать', 'макет', 'ambal', 'tipar']),
    'finance': ('Финансы и бюджет', ['финанс', 'бюджет', 'оплат', 'деньг', 'finan', 'buget']),
    'people': ('Люди и команда', ['персонал', 'сотрудник', 'коллектив', 'angaj', 'echip']),
    'it': ('Системы и доступ', ['систем', 'интеграц', 'доступ', 'сбой', 'sistem', 'integr', 'acces']),
}
SYSTEM_TERMS = ['1С', 'Excel', 'Google Таблицы', 'Google Sheets', 'ERP', 'DWH', 'LIMS', 'WMS', 'CRM',
                'почта', 'бумажные журналы', 'мессенджеры', 'Power BI', 'SAP', '1C']
DOCUMENT_TERMS = ['BOM', 'SOP', 'PO', 'DOC', 'SKU', 'регламент', 'инструкция', 'журнал', 'отчёт', 'заказ',
                  'сертификат', 'макет', 'досье', 'протокол', 'счёт', 'акт', 'спецификация', 'форма', 'шаблон']


def sentences(text):
    return [part.strip() for part in re.split(r'[\n\r.!?;]+', text) if part.strip()]


def significant(text):
    words = re.findall(r'[A-Za-zА-Яа-яЁёĂăÂâÎîȘșȚț]{3,}', text.lower().replace('ё', 'е'))
    return [word for word in words if word not in STOP and len(word) >= 4]


def analyze_about(text):
    """Детерминированный анализ: занятия только с доказательством из текста."""
    text = (text or '').strip()[:4000]
    parts = sentences(text)
    activities = []
    for key, (label, terms) in ACTIVITY_RULES.items():
        evidence = []
        matched = set()
        for sentence in parts:
            lower = sentence.lower().replace('ё', 'е')
            hits = [term for term in terms if term in lower]
            if hits:
                evidence.append(sentence[:240])
                matched.update(hits)
        if evidence:
            activities.append({'key': key, 'label': label, 'evidence': evidence[:2], 'keywords': sorted(matched)})
    activities.sort(key=lambda item: (-len(item['evidence']), item['label']))
    activities = activities[:7]
    counts = {}
    for word in significant(text):
        counts[word] = counts.get(word, 0) + 1
    keywords = [word for word, _ in sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:12]]
    systems = [term for term in SYSTEM_TERMS if term.lower().replace('ё', 'е') in text.lower().replace('ё', 'е')]
    documents = [term for term in DOCUMENT_TERMS if term.lower().replace('ё', 'е') in text.lower().replace('ё', 'е')]
    summary = 'Основные занятия: ' + ', '.join(item['label'] for item in activities[:5]) if activities else \
              'Ключевые слова: ' + ', '.join(keywords[:8]) if keywords else ''
    return {'summary': summary, 'activities': activities, 'systems': systems, 'documents': documents,
            'keywords': keywords, 'source': 'rules'}


def about_llm_prompt(text, lang, role_keys):
    return '\n'.join([
        'Ты анализируешь только описание работы сотрудника. Нельзя добавлять обязанности, которых нет в тексте.',
        'Выдели главные занятия, системы и документы. Для каждого занятия сохрани короткую точную цитату из исходного текста.',
        'Не оценивай человека, не предлагай решения, не повторяй конфиденциальные данные.',
        'Язык JSON-значений: ' + ('румынский' if lang == 'ro' else 'русский') + '. Функции сотрудника: ' + ','.join(role_keys) + '.',
        'Верни только JSON: {"summary":"1 предложение","activities":[{"key":"короткий английский идентификатор","label":"занятие",'
        '"evidence":["точная цитата из текста"],"keywords":["ключевое слово"]}],"systems":[],"documents":[],"keywords":[]}',
        'Описание работы сотрудника:\n' + text,
    ])


def extract_json(text):
    try:
        return json.loads(text)
    except Exception:
        match = re.search(r'\{[\s\S]*\}', text or '')
        if match:
            try:
                return json.loads(match.group(0))
            except Exception:
                return None
        return None


def analyze_about_with_llm(text, lang, role_keys, llm):
    """LLM уточняет правила; выбраковываем всё без цитаты из исходника."""
    base = analyze_about(text)
    if not (text or '').strip():
        return base
    try:
        payload = llm(about_llm_prompt(text, lang, role_keys))
        if isinstance(payload, str):
            payload = extract_json(payload)
        if not isinstance(payload, dict):
            return base
        activities = []
        lowered = text.lower().replace('ё', 'е')
        for item in payload.get('activities') or []:
            if not isinstance(item, dict):
                continue
            evidence = [str(value)[:240] for value in item.get('evidence') or [] if str(value).lower().replace('ё', 'е') in lowered]
            label = str(item.get('label') or '').strip()[:160]
            if label and evidence:
                activities.append({'key': str(item.get('key') or 'activity')[:60], 'label': label,
                                   'evidence': evidence[:2], 'keywords': [str(x)[:80] for x in item.get('keywords') or []][:8]})
        if not activities:
            return base
        return {'summary': str(payload.get('summary') or base['summary'])[:500],
                'activities': activities[:7],
                'systems': [str(x)[:80] for x in payload.get('systems') or []][:15],
                'documents': [str(x)[:80] for x in payload.get('documents') or []][:15],
                'keywords': [str(x)[:80] for x in payload.get('keywords') or []][:15],
                'source': 'ollama'}
    except Exception:
        return base


def focus_text(analysis):
    if not isinstance(analysis, dict):
        return ''
    parts = [analysis.get('summary') or '']
    parts.extend(analysis.get('keywords') or [])
    parts.extend(analysis.get('systems') or [])
    parts.extend(analysis.get('documents') or [])
    for item in analysis.get('activities') or []:
        parts.append(item.get('label') or '')
        parts.extend(item.get('keywords') or [])
        parts.extend(item.get('evidence') or [])
    return ' '.join(parts).lower().replace('ё', 'е')


def prioritize_questions(questions, analysis):
    """Релевантность внутри этапа: полный охват сохраняется, порядок не становится случайным."""
    if not isinstance(analysis, dict) or not analysis.get('activities'):
        return list(questions)
    focus = set(significant(focus_text(analysis)))
    stems = {word[:5] for word in focus}
    def score(question):
        words = set(significant(question['text']))
        return sum(1 for word in words if word[:5] in stems)
    return sorted(questions, key=lambda question: (question['phase'], -score(question), questions.index(question)))

#!/usr/bin/env python3
"""Единый источник ролевых профилей и вопросов Kodos для 22 функций."""
import json
from pathlib import Path

BASE = Path(__file__).resolve().parent
with (BASE / 'role_packs.json').open(encoding='utf-8') as source:
    ROLE_DATA = json.load(source)
ROLE_PACKS = ROLE_DATA['roles']

# Если сотрудник не подтвердил функцию явно, выбираем исполнительский профиль отдела.
DEFAULT_BY_DEPT = {
    'mgmt': '14', 'prod_dir': '01', 'planning': '02', 'prod_area': '03', 'operator': '04',
    'tech': '05', 'quality': '20', 'regulatory': '16', 'wh_raw': '06', 'wh_fg': '07',
    'procurement': '08', 'packaging': '17', 'sales': '09', 'crm': '10', 'marketing': '18',
    'logistics': '19', 'finance': '13', 'analytics': '12', 'hr': '21', 'it': '15', 'other': '00',
}
assert len(ROLE_PACKS) == 22
assert set(DEFAULT_BY_DEPT.values()) == set(ROLE_PACKS) - {'11'}  # 11 — явный выбор руководителя продаж
assert len({q['id'] for pack in ROLE_PACKS.values() for q in pack['questions']}) == 308
for key, pack in ROLE_PACKS.items():
    assert len(pack['questions']) == 14, key
    assert pack['dept'] in DEFAULT_BY_DEPT, key
    for question in pack['questions']:
        assert question['id'].startswith(key + '-'), (key, question['id'])
        assert 1 <= question['phase'] <= 5
        assert question['ru'].strip() and question['ro'].strip()


def role_keys(doc):
    """Основная функция первая, дополнительные — в порядке выбора сотрудника."""
    keys = []
    raw = doc.get('roleKeys')
    if isinstance(raw, list):
        for key in raw:
            key = str(key).strip()
            if key in ROLE_PACKS and key not in keys:
                keys.append(key)
    explicit = (doc.get('roleKey') or '').strip()
    if explicit in ROLE_PACKS and explicit not in keys:
        keys.insert(0, explicit)
    if not keys:
        keys = [DEFAULT_BY_DEPT.get(doc.get('dept') or 'other', '00')]
    return keys


def role_key(doc):
    return role_keys(doc)[0]


def role_pack(doc):
    return ROLE_PACKS[role_key(doc)]


def role_packs(doc):
    return [ROLE_PACKS[key] for key in role_keys(doc)]


def role_title(doc, lang='ru'):
    return ' + '.join(pack['title'].get(lang) or pack['title']['ru'] for pack in role_packs(doc))


def role_questions(doc, lang='ru'):
    return [{'id': item['id'], 'phase': item['phase'], 'text': item.get(lang) or item['ru']}
            for pack in role_packs(doc) for item in pack['questions']]


def role_coverage(doc):
    packs = role_packs(doc)
    asked = {m.get('questionKey') for m in doc.get('messages') or [] if isinstance(m, dict)}
    ids = [item['id'] for pack in packs for item in pack['questions'] if item['id'] in asked]
    return {'roleKey': role_key(doc), 'roleKeys': role_keys(doc), 'roleTitle': role_title(doc, 'ru'),
            'asked': len(ids), 'total': sum(len(pack['questions']) for pack in packs), 'questionIds': ids}

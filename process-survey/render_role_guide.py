#!/usr/bin/env python3
"""Формирует полный справочник должностей и машинный пакет для ERP №2."""
import json
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parent
DATA = json.loads((ROOT / 'role_packs.json').read_text(encoding='utf-8'))
OUT = ROOT / 'exports' / 'dolzhnosti-i-voprosy-balkan.md'
OUT_JSON = ROOT / 'exports' / 'dolzhnosti-i-voprosy-balkan.json'

SOURCES = [
    ('ICH Q10 — Pharmaceutical Quality System', 'https://database.ich.org/sites/default/files/Q10%20Guideline.pdf', 'Senior management has the ultimate responsibility'),
    ('ICH Q9(R1) — Quality Risk Management', 'https://database.ich.org/sites/default/files/ICH_Q9%28R1%29_Guideline_Step4_2022_1219.pdf', 'Risk management should be an ongoing part'),
    ('ICH Q8(R2) — Pharmaceutical Development', 'https://database.ich.org/sites/default/files/Q8%28R2%29%20Guideline.pdf', 'Quality by Design'),
    ('ICH Q12 — Product Lifecycle Management', 'https://database.ich.org/sites/default/files/Q12_Guideline_Step4_2019_1119.pdf', 'Established Conditions'),
    ('EU GMP Chapter 1 — Pharmaceutical Quality System', 'https://health.ec.europa.eu/system/files/2016-11/vol4-chap1_2013-01_en_0.pdf', 'Senior management has the ultimate responsibility'),
    ('EU GMP Chapter 2 — Personnel', 'https://health.ec.europa.eu/system/files/2016-11/2014-03_chapter_2_0.pdf', 'The heads of Production and Quality Control must be independent'),
    ('EU GMP Chapter 5 — Production', 'https://health.ec.europa.eu/system/files/2016-11/chapter_5_0.pdf', 'Packaging operations'),
    ('EU GMP Annex 11 — Computerised Systems', 'https://health.ec.europa.eu/system/files/2016-11/annex11_01-2011_en_0.pdf', 'User Requirements Specifications'),
    ('FDA 21 CFR Part 211 Subpart B', 'https://www.ecfr.gov/current/title-21/chapter-I/subchapter-C/part-211/subpart-B', 'There shall be a quality control unit'),
    ('EU Good Distribution Practice 2013/C 343/01', 'https://eur-lex.europa.eu/LexUriServ/LexUriServ.do?uri=OJ:C:2013:343:0001:0014:EN:PDF', 'The required storage conditions'),
    ('EMA — variations framework', 'https://www.ema.europa.eu/en/guidance-application-revised-variations-framework', 'Variations Guidelines'),
    ('EMA — falsified medicines', 'https://www.ema.europa.eu/en/human-regulatory-overview/public-health-threats/falsified-medicines-overview', 'unique identifier'),
    ('ILO ISCO-08', 'https://webapps.ilo.org/ilostat-files/ISCO/newdocs-08-2021/ISCO-08/ISCO-08%20EN%20Vol%201.pdf', 'Managers plan direct coordinate and evaluate'),
    ('ASCM SCOR Digital Standard', 'https://www.ascm.org/globalassets/ascm_website_assets/docs/scor/intro-and-front-matter-scor-digital-standard-2025.pdf', 'The macro-level SCOR processes'),
    ('APQC — Sales and Operations Planning', 'https://www.apqc.org/What-Is-Sales-and-Operations-Planning-SOP', 'The five phases are product review'),
    ('COSO — Internal Control', 'https://www.coso.org/guidance-on-ic', 'operations reporting and compliance'),
    ('NIST Cybersecurity Framework 2.0', 'https://nvlpubs.nist.gov/nistpubs/CSWP/NIST.CSWP.29.pdf', 'The integrity of backups'),
    ('MHRA GxP Data Integrity', 'https://assets.publishing.service.gov.uk/government/uploads/system/uploads/attachment_data/file/687246/MHRA_GxP_data_integrity_guide_March_edited_Final.pdf', 'Data transfer should be validated'),
    ('WHO TRS 1033 Annex 4 — Data Integrity', 'https://www.who.int/publications/m/item/annex-4-trs-1033', 'WHO Guideline on data integrity'),
    ('WHO Ethical Criteria for Medicinal Drug Promotion', 'https://iris.who.int/bitstreams/4d5f499f-3dcd-4eaa-8f9e-6d690ff93631/download', 'Comparison of products should be factual fair'),
    ('ISO 8000 — Data quality', 'https://www.iso.org/obp/ui#iso:std:iso:8000:-51:ed-1:v1:en:fn:2', 'An organization appoints a data governance authority'),
]


def web_citation(label, url, text):
    return '[%s](kimi-cite://web?url=%s&text=%s "citation")' % (label, quote(url, safe=''), quote(text, safe=''))


def bullets(items):
    return '\n'.join('- ' + item for item in items)


lines = [
    '# Должности и вопросы для ERP №2',
    '',
    '**Balkan Pharmaceuticals · 22 функции · 308 вопросов на русском и румынском**',
    '',
    'Документ объединяет международные практики и фактическую оргструктуру Kodos. Профиль — референтная модель, а не утверждение о работе конкретного сотрудника. Во время интервью подтверждаются реальные процессы, решения и доказательства.',
    '',
    '## Результат каждого интервью',
    '',
    bullets([
        'Подтверждённые назначение, ответственность и полномочия должности.',
        'Процессы, входы, выходы, решения, лимиты, заместители и запреты.',
        'Документы, версии, KPI, исключения, эскалации и доказательства.',
        'Требования к ERP с приоритетом и основанием из фактической работы.',
        'Покрытие всех 14 базовых тем по идентификаторам `questionKey`.',
        'Румынская версия вопросов включена в машинный пакет `role_packs.json`.',
    ]),
    '',
    '## Обязательная модель ERP №2',
    '',
    'Связь требования: **должность → вопрос → фактический процесс → документ → правило ERP → тест → владелец**. Данные сохраняются в резюме: `responsibilities`, `decision_rights`, `documents`, `kpis`, `exceptions`, `erp_requirements`. Экспорт содержит `role_key`, `role_title` и `role_coverage`.',
    '',
]
for key, pack in DATA['roles'].items():
    lines.extend([
        '---', '',
        '## %s · %s' % (key, pack['title']['ru']), '',
        '**Назначение:** ' + pack['mission']['ru'], '',
        '**Ориентиры:** ' + ', '.join(pack['practices']) + '.', '',
        '### Ответственность', '', bullets(pack['profile']['responsibilities']), '',
        '### Решения и полномочия', '', bullets(pack['profile']['decisions']), '',
        '### Документы и данные', '', bullets(pack['profile']['documents']), '',
        '### Кандидатные KPI', '', bullets(pack['profile']['kpis']), '',
        '_Целевые значения не назначаются до подтверждения формулы, источника и базовой линии Balkan._', '',
        '### Обязательные темы', '', bullets(pack['coverage_ru']), '',
        '### Вопросы интервью', '',
    ])
    for question in pack['questions']:
        lines.append('%d. **`%s` · этап %d** %s' % (int(question['id'].split('-')[-1]), question['id'], question['phase'], question['ru']))
    lines.append('')

lines.extend(['---', '', '## Международные источники', ''])
for label, url, text in SOURCES:
    lines.append('- ' + web_citation(label, url, text))
lines.extend([
    '',
    '## Ограничения',
    '',
    'Местные требования Молдовы и стран сбыта проверяются отдельно. Роль уполномоченного лица, сериализация, рекламные правила, учёт и сроки хранения не переносятся автоматически из других юрисдикций. Документ не заменяет юридическую оценку и фактические регламенты Balkan.',
    '',
])
OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text('\n'.join(lines), encoding='utf-8')
OUT_JSON.write_text(json.dumps(DATA, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
assert len(DATA['roles']) == 22
assert sum(len(pack['questions']) for pack in DATA['roles'].values()) == 308
for key, pack in DATA['roles'].items():
    assert '## %s · %s' % (key, pack['title']['ru']) in '\n'.join(lines)
print(json.dumps({'markdown': str(OUT), 'json': str(OUT_JSON), 'roles': 22, 'questions': 308}, ensure_ascii=False))

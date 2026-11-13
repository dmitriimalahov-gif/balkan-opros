#!/usr/bin/env python3
"""Реальная генерация RU/RO через рабочий процесс анкеты; запускать Python NumerOM."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import owner_voice
import voice_worker
expected_parts = ['Buna ziua!', 'Spunets-ne', 'ce sarcini', 'indeplinits', 'in fiecare zi?']
assert voice_worker.romanian_segments('Bună ziua! Spuneți-ne ce sarcini îndepliniți în fiecare zi?') == expected_parts
assert voice_worker.word_difference('Назовите три–пять задач', 'Назовите 3-5 задач', 'ru') == 0
assert voice_worker.word_difference('Какие пять–семь результатов', 'Какие 5-7 результатов', 'ru') == 0
items = [
    ('ru', 'Здравствуйте! Какие задачи вы выполняете каждый день?'),
    ('ru', 'Назовите три–пять самых частых или долгих задач. Как часто и сколько времени занимает каждая?'),
    ('ru', 'Какие пять–семь результатов компании вы считаете своими главными обязанностями и как проверяете их выполнение?'),
    ('ro', 'Bună ziua! Spuneți-ne ce sarcini îndepliniți în fiecare zi?'),
    ('ro', 'Bună ziua, Test! Vă voi pune câteva întrebări despre munca dumneavoastră — pe rând. Răspundeți cu cuvintele dumneavoastră, scurt sau detaliat, cum vă este comod.\n\nCum se numește rolul dumneavoastră real și pentru ce rezultat al activității răspundeți?'),
]
results = []
worker = voice_worker.Worker()
try:
    for lang, text in items:
        status, key = owner_voice.request_voice(text, lang)
        if status != 'working':
            raise AssertionError('Initial voice status: ' + status)
        path = owner_voice.VOICE_DIR / 'jobs' / (key + '.json')
        worker.process(path)
        final = owner_voice.voice_status(key)
        if final != 'ready':
            raise AssertionError('Voice generation failed: ' + lang + ' / ' + final)
        cache = owner_voice.VOICE_DIR / 'clips' / key
        ready = json.loads((cache / 'ready.json').read_text(encoding='utf-8'))
        audio = cache / 'audio.m4a'
        if audio.stat().st_size < 1000 or not ready['heard']:
            raise AssertionError('Empty voice result: ' + lang)
        results.append({'lang': lang, 'status': final, 'bytes': audio.stat().st_size,
                        'seconds': ready['seconds'], 'heard': ready['heard'],
                        'difference': ready['difference'], 'profile': ready['profile']})
finally:
    worker.unload()
(ROOT / 'run/worker-smoke-result.json').write_text(json.dumps(results, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
print(json.dumps(results, ensure_ascii=False, indent=2), flush=True)

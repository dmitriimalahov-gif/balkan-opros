#!/usr/bin/env python3
"""Реальная генерация приветствия RU/RO; запускать Python NumerOM."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import owner_voice
import server
import voice_worker

results = []
languages = sys.argv[1:] or ['ru', 'ro']
worker = voice_worker.Worker()
try:
    for lang in languages:
        status, key = owner_voice.request_voice(server.WELCOME_VOICE[lang], lang)
        if status != 'working':
            raise AssertionError('Initial welcome status: ' + status)
        worker.process(owner_voice.VOICE_DIR / 'jobs' / (key + '.json'))
        if owner_voice.voice_status(key) != 'ready':
            raise AssertionError('Welcome generation failed: ' + lang)
        cache = owner_voice.VOICE_DIR / 'clips' / key
        ready = json.loads((cache / 'ready.json').read_text(encoding='utf-8'))
        results.append({'lang': lang, 'status': 'ready', 'seconds': ready['seconds'],
                        'heard': ready['heard'], 'difference': ready['difference'],
                        'bytes': ready['bytes'], 'profile': ready['profile']})
finally:
    worker.unload()
(ROOT / 'run/welcome-worker-smoke-result.json').write_text(json.dumps(results, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
print(json.dumps(results, ensure_ascii=False, indent=2), flush=True)

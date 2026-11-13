#!/usr/bin/env python3
"""Локальная очередь озвучки вопросов голосом владельца NumerOM."""
from __future__ import annotations

import functools
import hashlib
import json
import os
import re
import secrets
import time
from pathlib import Path

BASE = Path(__file__).resolve().parent
VOICE_DIR = Path(os.environ.get('SURVEY_VOICE_DIR', str(BASE / 'data' / 'voice')))
RUN_DIR = Path(os.environ.get('SURVEY_RUN_DIR', str(BASE / 'run')))
HELPER = Path(os.environ.get('SURVEY_VOICE_HELPER', '/Users/brandbox/Developer/helper-voice'))
NUMEROM_LOCK = Path(os.environ.get(
    'SURVEY_NUMEROM_LOCK',
    '/Users/brandbox/Library/Application Support/NumerOM/runtime/backend/private/runtime/report-generation.lock',
))
MODEL = 'mlx-community/Qwen3-TTS-12Hz-1.7B-Base-bf16'
VOICE = 'dmitrii'
PROFILE = 'numerom-dmitrii-v2-clean'
TEMPO = 1.2
VERSION = 'balkan-owner-voice-v5-number-normalization'
MAX_TEXT = 4000


def _json_write(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_name('.' + path.name + '.' + secrets.token_hex(6) + '.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    temporary.chmod(0o600)
    temporary.replace(path)


def configured() -> bool:
    return all(path.is_file() for path in (
        HELPER / 'local/generate_local.py',
        HELPER / 'voice/dmitrii_ref.wav',
        HELPER / 'voice/dmitrii_ref.txt',
        NUMEROM_LOCK,
    ))


def voice_available() -> bool:
    """Не предлагаем кнопку, если локальный работник остановлен или эталон недоступен."""
    if not configured():
        return False
    try:
        heartbeat = RUN_DIR / 'voice-worker.heartbeat'
        return 0 <= time.time() - heartbeat.stat().st_mtime < 45
    except OSError:
        return False


@functools.lru_cache(maxsize=8)
def _reference_hash(mtime_ns: int, size: int) -> str:
    del mtime_ns, size
    return hashlib.sha256((HELPER / 'voice/dmitrii_ref.wav').read_bytes()).hexdigest()


def voice_key(text: str, lang: str) -> str:
    if lang not in ('ru', 'ro') or not isinstance(text, str) or not 1 <= len(text.strip()) <= MAX_TEXT:
        raise ValueError('voice_text')
    reference = HELPER / 'voice/dmitrii_ref.wav'
    stat = reference.stat()
    ref_hash = _reference_hash(stat.st_mtime_ns, stat.st_size)
    payload = json.dumps([VERSION, text.strip(), lang, ref_hash, MODEL, VOICE, PROFILE, TEMPO],
                         ensure_ascii=False, separators=(',', ':'))
    return hashlib.sha256(payload.encode('utf-8')).hexdigest()


def voice_status(key: str) -> str:
    if not re.fullmatch(r'[a-f0-9]{64}', key or ''):
        return 'not_found'
    cache = VOICE_DIR / 'clips' / key
    audio = cache / 'audio.m4a'
    if (cache / 'ready.json').is_file() and audio.is_file() and audio.stat().st_size > 0:
        return 'ready'
    if (cache / 'failed.json').is_file():
        return 'failed'
    if (VOICE_DIR / 'jobs' / (key + '.json')).is_file() or (cache / 'working.json').is_file():
        return 'working'
    return 'not_found'


def request_voice(text: str, lang: str) -> tuple[str, str]:
    key = voice_key(text, lang)
    status = voice_status(key)
    if status != 'not_found':
        return status, key
    job = {
        'id': 'survey-' + key[:16],
        'hash': key,
        'text': text.strip(),
        'lang': lang,
        'voice': VOICE,
        'profile': PROFILE,
        'model': MODEL,
        'tempo': TEMPO,
        'createdAt': time.time(),
    }
    _json_write(VOICE_DIR / 'jobs' / (key + '.json'), job)
    return 'working', key


def voice_audio_path(key: str) -> Path | None:
    if voice_status(key) != 'ready':
        return None
    return VOICE_DIR / 'clips' / key / 'audio.m4a'

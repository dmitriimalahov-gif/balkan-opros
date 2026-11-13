#!/usr/bin/env python3
"""Работник локальной озвучки Balkan тем же голосом dmitrii, что и NumerOM.

Запускается Python голосового окружения NumerOM. Тяжёлая генерация защищена общей
блокировкой NumerOM, поэтому Ollama, видео и NumerOM не работают одновременно с TTS.
"""
from __future__ import annotations

import argparse
import difflib
import fcntl
import gc
import hashlib
import importlib
import importlib.util
import json
import os
import re
import subprocess
import sys
import threading
import time
import unicodedata
from pathlib import Path

os.environ['HF_HUB_OFFLINE'] = '1'
os.environ['HF_HUB_DISABLE_TELEMETRY'] = '1'

import owner_voice

HELPER = owner_voice.HELPER
sys.path.insert(0, str(HELPER / 'local'))
spec = importlib.util.spec_from_file_location('helper_voice', HELPER / 'local/generate_local.py')
voice = importlib.util.module_from_spec(spec)
spec.loader.exec_module(voice)
whisper_cache = importlib.import_module('mlx_whisper.transcribe').ModelHolder
voice.mx.set_cache_limit(256 * 1024 * 1024)
WHISPER = 'mlx-community/whisper-large-v3-turbo'
IDLE_UNLOAD = 60


def segments(text: str, limit: int = 330) -> list[str]:
    """Короткие фразы для устойчивого клонирования, без разрыва слов."""
    sentences = re.split(r'(?<=[.!?;])\s+|\n+', text.strip())
    chunks, current = [], ''
    for sentence in sentences:
        sentence = sentence.strip()
        if not sentence:
            continue
        if sentence[-1] not in '.!?;':
            sentence += '.'
        if len(sentence) > limit:
            words, sentence = sentence.split(), ''
            for word in words:
                if len(sentence) + len(word) > limit - 1:
                    if current:
                        chunks.append(current)
                        current = ''
                    if sentence:
                        chunks.append(sentence)
                    sentence = ''
                sentence = (sentence + ' ' + word).strip()
        if current and len(current) + len(sentence) + 1 > limit:
            chunks.append(current)
            current = ''
        current = (current + ' ' + sentence).strip()
    if current:
        chunks.append(current)
    return chunks


def spoken_romanian(text: str) -> str:
    """Фонетическая запись только для TTS; на экране остаётся исходный румынский."""
    return (text.replace('ți', 'ts').replace('ţi', 'ts').replace('ȚI', 'TS').replace('ŢI', 'TS')
            .replace('ț', 'ts').replace('ţ', 'ts').replace('Ț', 'Ts').replace('Ţ', 'Ts')
            .replace('ș', 'sh').replace('ş', 'sh').replace('Ș', 'Sh').replace('Ş', 'Sh')
            .replace('ă', 'a').replace('Ă', 'A').replace('â', 'i').replace('Â', 'I')
            .replace('î', 'i').replace('Î', 'I'))


def romanian_segments(text: str) -> list[str]:
    """Короткие смысловые части: клитика, группа до двух слов, предложная группа до трёх."""
    chunks = []
    prepositions = {'in', 'la', 'cu', 'de', 'pe', 'pentru'}
    for sentence in re.split(r'(?<=[.!?;])\s+|\n+', spoken_romanian(text.strip())):
        current, limit = [], 2
        for word in sentence.split():
            normalized = word.lower().strip(',.!?;:')
            if normalized in prepositions and current:
                chunks.append(' '.join(current))
                current = []
            if not current:
                limit = 3 if normalized in prepositions else 2
            current.append(word)
            if len(current) >= limit or word.lower().endswith('-ne'):
                chunks.append(' '.join(current))
                current, limit = [], 2
        if current:
            chunks.append(' '.join(current))
    merged = []
    for chunk in chunks:
        if re.search(r'[A-Za-z0-9]', chunk):
            merged.append(chunk)
        elif merged:
            merged[-1] += ' ' + chunk
    return merged


RU_NUMBERS = {
    'ноль': '0', 'один': '1', 'одна': '1', 'одно': '1', 'одного': '1', 'одной': '1',
    'два': '2', 'две': '2', 'двух': '2', 'три': '3', 'трех': '3', 'четыре': '4', 'четырех': '4',
    'пять': '5', 'пяти': '5', 'шесть': '6', 'шести': '6', 'семь': '7', 'семи': '7',
    'восемь': '8', 'восьми': '8', 'девять': '9', 'девяти': '9', 'десять': '10', 'десяти': '10',
    'одиннадцать': '11', 'двенадцать': '12', 'тринадцать': '13', 'четырнадцать': '14',
    'пятнадцать': '15', 'шестнадцать': '16', 'семнадцать': '17', 'восемнадцать': '18',
    'девятнадцать': '19', 'двадцать': '20', 'тридцать': '30', 'сорок': '40',
    'пятьдесят': '50', 'шестьдесят': '60', 'семьдесят': '70', 'восемьдесят': '80',
    'девяносто': '90', 'сто': '100',
}


def word_difference(expected: str, heard: str, lang: str) -> float:
    def words(text: str) -> list[str]:
        text = text.lower().replace('ё', 'е')
        if lang == 'ro':
            text = ''.join(char for char in unicodedata.normalize('NFKD', text) if not unicodedata.combining(char))
        tokens = re.findall(r'[a-zа-я]+|\d+', text)
        return [RU_NUMBERS.get(token, token) for token in tokens] if lang == 'ru' else tokens
    left, right = words(expected), words(heard)
    if not left or not right:
        return 1.0
    return 1 - difflib.SequenceMatcher(None, left, right).ratio()


def local_whisper_model() -> str:
    from huggingface_hub import snapshot_download
    path = Path(snapshot_download(repo_id=WHISPER, local_files_only=True))
    if not (path / 'config.json').is_file() or not any((path / name).is_file() for name in ('weights.safetensors', 'weights.npz')):
        raise FileNotFoundError('Incomplete local Whisper model')
    return str(path)


class Worker:
    def __init__(self):
        self.model = None
        self.whisper_model = None
        self.last_activity = time.time()

    def unload(self):
        self.model = None
        self.whisper_model = None
        whisper_cache.model = None
        whisper_cache.model_path = None
        gc.collect()
        voice.mx.clear_cache()

    def generate(self, job: dict, cache: Path) -> dict:
        text, lang, key = job['text'], job['lang'], job['hash']
        reference = HELPER / 'voice/dmitrii_ref.wav'
        reference_text = (HELPER / 'voice/dmitrii_ref.txt').read_text(encoding='utf-8').strip()
        parts = segments(text) if lang == 'ru' else romanian_segments(text)
        best = None
        # Qwen3-TTS не имеет официального румынского кода; итальянская фонетическая
        # подсказка сохраняет тембр клона, а правильность проверяет румынский Whisper.
        hint = 'russian' if lang == 'ru' else 'italian'
        seeds = (17, 7, 101) if lang == 'ru' else (101, 17, 7)
        for attempt in range(3):
            if self.model is None:
                self.model = voice.load_model(owner_voice.MODEL)
            sr = self.model.sample_rate
            audio_parts = []
            for index, part in enumerate(parts):
                raw, last_error = None, None
                for empty_retry in range(3):
                    voice.mx.random.seed((seeds[attempt] + (index * 13 if lang == 'ru' else 0) + empty_retry * 31) % (2 ** 32))
                    try:
                        generated = list(self.model.generate(
                            text=part, ref_audio=str(reference), ref_text=reference_text,
                            lang_code=hint, temperature=.75, top_p=.9, max_tokens=520,
                        ))
                        candidate = voice.np.concatenate([voice.np.asarray(item.audio) for item in generated]).astype(voice.np.float32)
                        if candidate.size:
                            raw = candidate
                            break
                        last_error = 'empty audio'
                    except Exception as error:
                        last_error = error
                    print('RETRY FRAGMENT', lang, index + 1, empty_retry + 1, str(last_error), flush=True)
                    gc.collect()
                    voice.mx.clear_cache()
                if raw is None:
                    raise ValueError('Empty audio for fragment ' + str(index + 1) + ': ' + str(last_error))
                cleaned = voice.soft_edges(voice.gate(voice.highpass(raw, sr), sr), sr)
                if audio_parts:
                    audio_parts.append(voice.np.zeros(round(sr * (.38 if lang == 'ru' else .18)), dtype=voice.np.float32))
                audio_parts.append(cleaned)
                del generated, raw, cleaned
                gc.collect()
                voice.mx.clear_cache()
            audio = voice.np.concatenate(audio_parts)
            audio = voice.loudness(audio)
            audio = voice.stretch(audio, sr, owner_voice.TEMPO)
            voice.sf.write(cache / 'candidate.wav', audio, sr)
            if self.whisper_model is None:
                self.whisper_model = local_whisper_model()
            heard = voice.mlx_whisper.transcribe(
                voice.to16k(audio, sr), path_or_hf_repo=self.whisper_model,
                language='ru' if lang == 'ru' else 'ro',
            )['text'].strip()
            difference = word_difference(text, heard, lang)
            print('CHECK', job['id'], lang, 'attempt', attempt + 1, 'difference', round(difference, 4), flush=True)
            if best is None or difference < best[0]:
                best = (difference, heard, audio, sr)
            if difference <= (.12 if lang == 'ru' else .20):
                break
            del audio
            gc.collect()
            voice.mx.clear_cache()
        difference, heard, audio, sr = best
        if difference > (.12 if lang == 'ru' else .20):
            voice.sf.write(cache / 'review.wav', audio, sr)
            raise ValueError('Pronunciation review required: ' + str(round(difference, 4)) + '; heard: ' + heard)
        voice.sf.write(cache / 'master.wav', audio, sr)
        pending = cache / 'audio.pending.m4a'
        pending.unlink(missing_ok=True)
        subprocess.run(['/usr/bin/afconvert', '-f', 'm4af', '-d', 'aac', '-b', '64000',
                        str(cache / 'master.wav'), str(pending)], check=True)
        pending.replace(cache / 'audio.m4a')
        ready = {
            'hash': key, 'lang': lang, 'voice': owner_voice.VOICE, 'profile': owner_voice.PROFILE,
            'model': owner_voice.MODEL, 'tempo': owner_voice.TEMPO,
            'seconds': round(len(audio) / sr, 2), 'bytes': (cache / 'audio.m4a').stat().st_size,
            'sha256': hashlib.sha256((cache / 'audio.m4a').read_bytes()).hexdigest(),
            'heard': heard, 'difference': round(difference, 5),
            'pronunciationReview': 'pending_human_listening',
        }
        owner_voice._json_write(cache / 'ready.json', ready)
        for temporary in ('candidate.wav', 'master.wav'):
            (cache / temporary).unlink(missing_ok=True)
        return ready

    def process(self, path: Path, retry_failed: bool = False) -> bool:
        key = path.stem
        cache = owner_voice.VOICE_DIR / 'clips' / key
        if owner_voice.voice_status(key) == 'ready':
            path.unlink(missing_ok=True)
            return False
        if (cache / 'failed.json').is_file() and not retry_failed:
            return False
        try:
            job = json.loads(path.read_text(encoding='utf-8'))
            assert job.get('hash') == key and re.fullmatch(r'[a-f0-9]{64}', key)
            assert job.get('voice') == owner_voice.VOICE and job.get('model') == owner_voice.MODEL
            assert job.get('lang') in ('ru', 'ro')
            assert isinstance(job.get('text'), str) and 1 <= len(job['text']) <= owner_voice.MAX_TEXT
        except (OSError, ValueError, AssertionError, json.JSONDecodeError):
            return False
        cache.mkdir(parents=True, exist_ok=True, mode=0o700)
        owner_voice._json_write(cache / 'working.json', {'startedAt': time.time(), 'id': job.get('id')})
        (cache / 'failed.json').unlink(missing_ok=True)
        print('START', job.get('id'), job['lang'], flush=True)
        try:
            with voice.heavy_slot():
                ready = self.generate(job, cache)
            (cache / 'failed.json').unlink(missing_ok=True)
            path.unlink(missing_ok=True)
            print('READY', job.get('id'), ready['seconds'], 'seconds', flush=True)
        except Exception as error:
            owner_voice._json_write(cache / 'failed.json', {'error': str(error), 'at': time.time()})
            print('FAILED', job.get('id'), str(error), flush=True)
        finally:
            (cache / 'working.json').unlink(missing_ok=True)
            self.last_activity = time.time()
            gc.collect()
            voice.mx.clear_cache()
        return True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--watch', action='store_true')
    parser.add_argument('--retry-failed', action='store_true')
    args = parser.parse_args()
    owner_voice.VOICE_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
    owner_voice.RUN_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
    lock = (owner_voice.VOICE_DIR / 'worker.lock').open('w')
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    stop = threading.Event()

    def heartbeat():
        target = owner_voice.RUN_DIR / 'voice-worker.heartbeat'
        while not stop.is_set():
            target.write_text(str(time.time()), encoding='ascii')
            target.chmod(0o600)
            stop.wait(2)

    thread = threading.Thread(target=heartbeat, daemon=True)
    thread.start()
    worker = Worker()
    print('VOICE WORKER STARTED', owner_voice.VOICE_DIR, flush=True)
    try:
        while True:
            jobs = sorted((owner_voice.VOICE_DIR / 'jobs').glob('*.json'), key=lambda path: path.stat().st_mtime)
            worked = False
            for path in jobs:
                worked = worker.process(path, retry_failed=args.retry_failed) or worked
                if worked:
                    break
            if not args.watch and not worked:
                break
            if worker.model is not None and time.time() - worker.last_activity > IDLE_UNLOAD:
                worker.unload()
            stop.wait(1)
    finally:
        stop.set()
        thread.join(timeout=5)
        worker.unload()
        print('VOICE WORKER STOPPED', flush=True)


if __name__ == '__main__':
    main()

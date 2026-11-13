# Опрос «Карта процессов Balkan» на сервере — ранбук

С 13.11.2026 опрос работает на сервере `root@llm.myoguz.xyz` под адресом **https://poll.erp.numer.om**.
Постоянная ссылка сотрудникам не меняется: https://dmitriimalahov-gif.github.io/balkan-opros/ (обёртка
встраивает опрос iframe'ом по адресу из `current.json` = `https://poll.erp.numer.om`). Панель: тот же адрес + `#admin`
или напрямую `https://poll.erp.numer.om/admin`.

## Состав

| Что | Где |
|---|---|
| Код + данные | `/opt/balkan-opros/` (код root:root, только чтение в контейнере) |
| SQLite, вложения, голос | `/opt/balkan-opros/data/` (uid 10001, 700) |
| Пароль панели | `/opt/balkan-opros/ADMIN_PASSWORD.txt` (uid 10001, 600) — не печатать |
| Ключ основного LLM API | `/opt/balkan-opros/run/llm.env` (`LLM_BASE_URL`, `LLM_API_KEY`; root, 600) — `env_file` compose |
| Признак «постоянная ссылка опубликована» | `/opt/balkan-opros/run/pushed-url` (нужен для `stableUrl` в API) |
| Compose / Dockerfile / run.py | `/opt/balkan-opros/deploy/` (копия этого каталога) |
| Модели Ollama | `/opt/balkan-opros/ollama/` |
| nginx | `/etc/nginx/sites-available/poll.erp.numer.om.conf` (+ симлинк в sites-enabled) |
| Сертификат | `/etc/letsencrypt/live/poll.erp.numer.om/` (webroot `/var/www/certbot`, общий аккаунт certbot) |
| Копия БД до переключения | `/opt/balkan-opros/backup-precutover/` (предварительная копия, этап «а») |

Контейнеры (`docker compose -p balkan-opros`):
- `balkan-opros-survey` — `python:3.12-slim` + зависимости; `deploy/run.py` запускает `server.py`, подменяя адрес
  прослушивания на 0.0.0.0 внутри контейнера (код не меняется). Наружу — только `127.0.0.1:18795`. 2 ГБ, 4 CPU.
- `balkan-opros-ollama` — `ollama/ollama`, модель `qwen3.5:9b`, `num_ctx` 16384 (задаёт server.py). Порт наружу не
  публикуется, доступ только из внутренней сети compose (`http://ollama:11434`). **CPU**: GPU сервера занята движком
  strata (~23,4 из 24 ГБ), nvidia-container-toolkit не установлен. 12 ГБ, 8 CPU. Ollama — резерв: основная модель
  `qwen3.8-flash-next-iq3_s` через OpenAI-совместимый API `LLM_BASE_URL` (litellm этого же сервера). Модель грузится
  в память только при сбое API (`ai_available()` = true, пока задан ключ API).

## Управление

```bash
cd /opt/balkan-opros/deploy
docker compose ps                       # оба healthy
docker compose logs -f survey           # без тел и токенов (server.py не логирует запросы)
docker compose restart survey
curl -s https://poll.erp.numer.om/api/config      # {"ai": true, ...}
```

Обновление кода (с Mac): `rsync -a --exclude pages --exclude run --exclude data --exclude ADMIN_PASSWORD.txt
--exclude __pycache__ ~/erp2-inbox/process-survey/ root@llm.myoguz.xyz:/opt/balkan-opros/`, затем
`chown -R root:root` для кода и `docker compose restart survey`. Пересборка образа нужна только при смене зависимостей
(`docker compose build survey && docker compose up -d survey`).

Смена пароля панели: записать новый в `ADMIN_PASSWORD.txt` (uid 10001, 600) → `docker compose restart survey`.

## Бэкап

```bash
docker exec balkan-opros-survey python3 -c "import sqlite3;s=sqlite3.connect('/app/data/survey.db');d=sqlite3.connect('/app/data/backup.db');s.backup(d)"
# затем забрать data/backup.db + data/attachments + data/voice
```

## Как развёрнуто (повторить с нуля)

1. `mkdir -p /opt/balkan-opros/{data,run,ollama}`; код и `deploy/` — rsync с Mac; `data/survey.db` — только через
   `sqlite3 .backup` (не копировать живой файл с -wal); `chown -R 10001:10001 data run ADMIN_PASSWORD.txt`;
   `chmod 600 ADMIN_PASSWORD.txt run/llm.env` (llm.env — root); `echo https://poll.erp.numer.om > run/pushed-url`.
2. `cd deploy && docker compose up -d --build`; `docker exec balkan-opros-ollama ollama pull qwen3.5:9b`.
3. nginx: сначала `nginx/poll.erp.numer.om.http-only.conf` → `nginx -t && systemctl reload nginx` →
   `certbot certonly --webroot -w /var/www/certbot -d poll.erp.numer.om --non-interactive --agree-tos` (без e-mail,
   аккаунт уже есть) → сразу `nginx/poll.erp.numer.om.conf` (80→301, 443 + HSTS) → `nginx -t && reload`.
   Продление: certbot.timer; для этого сертификата `renew_hook = systemctl reload nginx` в renewal-конфиге.
4. `client_max_body_size 16m`: вложения идут частями по 8 МиБ (`UPLOAD_CHUNK`), JSON ≤ 600 КБ (`MAX_BODY`);
   файл ≤ 500 МБ, ≤ 5 ГиБ на интервью — следить за диском. `proxy_read_timeout 360s` (ИИ до 300 с).
   nginx затирает клиентские `CF-Connecting-IP`/`X-Forwarded-For` — от них зависят лимиты частоты и блок подбора пароля.

## Переключение 13.11.2026 (сделано)

Mac: `launchctl bootout` + `launchctl disable gui/$UID/com.balkan.process-survey` (plist НЕ удалён), `./start.sh stop`
(сервер, работник голоса, туннель, сторож). Финальная копия `sqlite3 .backup` при остановленном сервере → сервер.
До/после: интервью 46/46, документов базы знаний 12/12, файлов вложений 13/13, файлов голоса 97/97.
`pages/index.html`: валидатор адреса пропускает `https://poll.erp.numer.om` (и по-прежнему `*.trycloudflare.com`
для отката); `pages/current.json` = `https://poll.erp.numer.om`; запушено в `dmitriimalahov-gif/balkan-opros`.

⚠️ Не запускать `./start.sh start` на Mac: сторож поднимет туннель и перепишет `current.json` на trycloudflare —
ответы пойдут в старую базу Mac.

## Откат на Mac

1. Остановить приём на сервере: `docker compose stop survey` (nginx отдаст 502).
2. Забрать данные: `sqlite3 .backup` из `/opt/balkan-opros/data/survey.db` (или python-бэкап выше) + rsync
   `data/attachments`, `data/voice` → `~/erp2-inbox/process-survey/data/` (старую базу Mac сначала переименовать).
3. На Mac: `launchctl enable gui/$UID/com.balkan.process-survey`, `./start.sh start` — сторож сам опубликует адрес
   туннеля в `current.json` (обёртка его примет).

## Что не работает на Linux

- **Голос интервьюера** (Qwen3-TTS + Whisper на MLX, профиль NumerOM, `voice_worker.py`) — только Apple Silicon/
  окружение NumerOM; на сервере `ownerVoice: false`, кнопка озвучки скрыта. Уже готовые клипы (`data/voice/clips`)
  перенесены, но не выдаются (API требует живого работника). Голосовой **ввод** работает: это SpeechRecognition браузера.
- **OCR изображений и сканов PDF** (`ocr_vision.swift`, macOS Vision) — нет; такие документы получат статус
  `failed` (`document_read_failed`). Текстовые PDF работают (pypdf, при пустом слое — `pdftotext` из poppler,
  симлинк на путь Homebrew в образе).
- **`.doc`** (старый Word, `textutil`) — нет; `.docx`, `.xlsx`, `.xls`, `.csv`, Google Таблицы — работают.

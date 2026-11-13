#!/bin/bash
# Сторож публичной ссылки опроса (запускать раз в 2 минуты: launchd или цикл в start.sh).
# Если публичный адрес не отвечает 3 проверки подряд — перезапускает туннель (адрес станет новым).
# Новый адрес пишет в run/last-url и показывает уведомлением macOS; панель руководителя видит его сама.
set -uo pipefail
BASE=/Users/brandbox/erp2-inbox/process-survey
RUN="$BASE/run"; LOG="$RUN/watchdog.log"; FAILS="$RUN/fail-count"; LAST="$RUN/last-url"
export PATH="/Users/brandbox/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
log() { echo "$(date '+%F %T') $*" >> "$LOG"; }
code() { curl -s -m 10 -o /dev/null -w '%{http_code}' "$1" 2>/dev/null; }

# сам сервер лежит — туннель не трогаем
[[ "$(code http://127.0.0.1:8795/healthz)" == 200 ]] || { log "сервер не отвечает локально"; exit 0; }

# Локальный голос владельца должен восстанавливаться вместе с опросом.
if [[ ! -f "$RUN/voice.pid" ]] || ! kill -0 "$(cat "$RUN/voice.pid" 2>/dev/null)" 2>/dev/null; then
  "$BASE/start.sh" start >/dev/null 2>&1
  log "работник голоса перезапущен"
fi

# Исходный код синхронизируется отдельно от адреса туннеля; ошибка кода не мешает работе ссылки.
"$BASE/sync-code.sh" >> "$RUN/code-sync.log" 2>&1 || log "синхронизация кода отложена, повторю"

# Постоянная ссылка (как у Helper): адрес туннеля → pages/current.json → push в GitHub Pages.
# Неудачный push повторяется на следующей проверке (run/pushed-url хранит последний опубликованный адрес).
PAGES="$BASE/pages"; PUSHED="$RUN/pushed-url"
publish() {
  [[ -d "$PAGES/.git" ]] && git -C "$PAGES" remote get-url origin >/dev/null 2>&1 || return 0
  printf '{"url": "%s", "updatedAt": "%s"}\n' "$1" "$(date -u +%FT%TZ)" > "$PAGES/current.json"
  git -C "$PAGES" -c user.name="dmitriimalahov-gif" -c user.email="dmitrii.malahov@gmail.com" \
    commit -q -m "current.json: адрес опроса $1" -- current.json >/dev/null 2>&1 || true
  # опубликовано, только если в отправленном коммите действительно новый адрес
  if git -C "$PAGES" push -q origin main >>"$LOG" 2>&1 && git -C "$PAGES" show origin/main:current.json 2>/dev/null | grep -qF "$1"; then
    echo "$1" > "$PUSHED"; log "постоянная ссылка → $1"
  else
    log "push постоянной страницы не удался, повторю"
  fi
}

url=$(grep -aoE 'https://[a-z0-9-]+\.trycloudflare\.com' "$RUN/tunnel.log" 2>/dev/null | tail -n1)
if [[ -n "$url" && "$(code "$url/healthz")" == 200 ]]; then
  echo 0 > "$FAILS"
  if [[ "$url" != "$(cat "$LAST" 2>/dev/null)" ]]; then
    echo "$url" > "$LAST"
    log "адрес: $url"
  fi
  [[ "$url" != "$(cat "$PUSHED" 2>/dev/null)" ]] && publish "$url"
  exit 0
fi
n=$(( $(cat "$FAILS" 2>/dev/null || echo 0) + 1 ))
echo "$n" > "$FAILS"
log "адрес не отвечает ($n/3): ${url:-адреса нет}"
if (( n >= 3 )); then
  echo 0 > "$FAILS"
  "$BASE/start.sh" restart-tunnel
  log "туннель перезапущен"
fi

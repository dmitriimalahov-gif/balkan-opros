#!/bin/bash
# Управление опросом «Карта процессов Balkan» без автозапуска.
#   ./start.sh start           — поднять сервер (127.0.0.1:8795), туннель Cloudflare и сторожа
#   ./start.sh stop            — остановить всё
#   ./start.sh status          — что запущено и какая сейчас публичная ссылка
#   ./start.sh restart-tunnel  — новый туннель (новый адрес)
# Процессы живут до перезагрузки Mac. Автозапуск после перезагрузки — install-autostart.sh.
set -uo pipefail
BASE=/Users/brandbox/erp2-inbox/process-survey
RUN="$BASE/run"
PY=/Library/Frameworks/Python.framework/Versions/3.12/bin/python3
VOICE_PY="/Users/brandbox/Library/Application Support/NumerOM/runtime/backend/.service-voice-venv/bin/python"
CF=/Users/brandbox/.local/bin/cloudflared
mkdir -p "$RUN"
if [[ -f "$RUN/llm.env" ]]; then
  set -a; source "$RUN/llm.env"; set +a
fi

alive() { [[ -f "$RUN/$1.pid" ]] && kill -0 "$(cat "$RUN/$1.pid")" 2>/dev/null; }
stop_one() { alive "$1" && kill "$(cat "$RUN/$1.pid")" 2>/dev/null; rm -f "$RUN/$1.pid"; }

start_server() {
  alive server && return
  nohup "$PY" "$BASE/server.py" >> "$RUN/server.log" 2>&1 &
  echo $! > "$RUN/server.pid"
}
start_voice() {
  alive voice && return
  [[ -x "$VOICE_PY" && -f "$BASE/voice_worker.py" ]] || return
  rm -f "$RUN/voice-worker.heartbeat"
  nohup "$VOICE_PY" -B "$BASE/voice_worker.py" --watch >> "$RUN/voice-worker.log" 2>&1 &
  echo $! > "$RUN/voice.pid"
}
start_tunnel() {
  alive tunnel && return
  : > "$RUN/tunnel.log"
  nohup "$CF" tunnel --no-autoupdate --url http://127.0.0.1:8795 >> "$RUN/tunnel.log" 2>&1 &
  echo $! > "$RUN/tunnel.pid"
}
start_watch() {
  alive watch && return
  nohup bash -c "while true; do sleep 120; '$BASE/watchdog.sh'; done" >/dev/null 2>&1 &
  echo $! > "$RUN/watch.pid"
}
url() { grep -aoE 'https://[a-z0-9-]+\.trycloudflare\.com' "$RUN/tunnel.log" 2>/dev/null | tail -n1; }

case "${1:-status}" in
  start) start_server; start_voice; start_tunnel; start_watch
         for _ in $(seq 1 30); do [[ -n "$(url)" ]] && break; sleep 1; done
         echo "анкета: $(url)/"; echo "панель: $(url)/admin" ;;
  stop) stop_one watch; stop_one tunnel; stop_one voice; stop_one server; echo "остановлено" ;;
  restart-tunnel) stop_one tunnel; start_tunnel
         for _ in $(seq 1 30); do [[ -n "$(url)" ]] && break; sleep 1; done; echo "новый адрес: $(url)" ;;
  status) for p in server voice tunnel watch; do alive $p && echo "$p: работает" || echo "$p: не запущен"; done
          echo "ссылка: $(url)" ;;
  *) echo "использование: $0 start|stop|status|restart-tunnel"; exit 1 ;;
esac

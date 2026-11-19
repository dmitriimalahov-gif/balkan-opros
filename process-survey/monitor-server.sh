#!/bin/bash
# Сторож постоянного сервера опроса и ИИ-модели интервьюера. Запускается LaunchAgent
# com.balkan.process-survey-server-monitor раз в 5 минут (установка: ./install-server-monitor-autostart.sh).
# Уведомление на Mac — один раз после нескольких сбоев подряд и один раз при восстановлении.
# /healthz опроса не видит падения модели (резерв Ollama держит "ai": true), поэтому модель проверяется отдельно.
set -uo pipefail
export PATH='/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin'

SURVEY_URL="${SURVEY_HEALTH_URL:-https://poll.erp.numer.om/healthz}"
LLM_URL="${SURVEY_LLM_URL:-https://llm.myoguz.xyz/models}"
ONLINE_URL="${SURVEY_ONLINE_URL:-https://www.apple.com/library/test/success.html}"
STATE="${SURVEY_MONITOR_STATE:-/Users/brandbox/erp2-inbox/process-survey/run}"
FAILS_TO_ALERT="${SURVEY_MONITOR_FAILS:-2}"
TIMEOUT="${SURVEY_MONITOR_TIMEOUT:-20}"

log() {
  echo "$(date '+%F %T') $*"
}

notify() {
  local title="$1" text="$2"
  echo "УВЕДОМЛЕНИЕ: $title — $text"
  if [[ "${SURVEY_NOTIFY:-1}" == '1' && -x /usr/bin/osascript ]]; then
    /usr/bin/osascript -e 'on run argv' \
      -e 'display notification (item 2 of argv) with title (item 1 of argv) sound name "Basso"' \
      -e 'end run' -- "$title" "$text" >/dev/null 2>&1 || true
  fi
}

survey_alive() {
  curl -fsS -m "$TIMEOUT" "$SURVEY_URL" 2>/dev/null | grep -Eq '"ok": *true'
}

# Без ключа API живая модель отвечает 401/404; 5xx или отсутствие ответа означает, что модель не работает.
llm_alive() {
  local code
  code=$(curl -s -o /dev/null -m "$TIMEOUT" -w '%{http_code}' "$LLM_URL" 2>/dev/null) || code=000
  [[ "$code" =~ ^[1-4][0-9][0-9]$ ]]
}

# check <ключ> <название для человека> <функция проверки>
check() {
  local key="$1" title="$2" probe="$3"
  local fails_file="$STATE/monitor-$key.fails" alert_file="$STATE/monitor-$key.alerted" fails=0
  [[ -f "$fails_file" ]] && fails=$(<"$fails_file")

  if "$probe"; then
    if [[ -f "$alert_file" ]]; then
      rm -f "$alert_file"
      notify "Balkan: $title снова работает" "Проверка в $(date '+%H:%M') прошла успешно"
      log "$key: восстановлено"
    fi
    rm -f "$fails_file"
    return 0
  fi

  fails=$((fails + 1))
  echo "$fails" > "$fails_file"
  if (( fails >= FAILS_TO_ALERT )) && [[ ! -f "$alert_file" ]]; then
    touch "$alert_file"
    notify "Balkan: $title не отвечает" "Сбой $fails проверки подряд. Подробности: run/server-monitor.log"
    log "$key: сбой, $fails проверки подряд"
  fi
}

mkdir -p "$STATE"
# Mac без интернета — не повод для тревоги о сервере.
if ! curl -fsS -o /dev/null -m "$TIMEOUT" "$ONLINE_URL" 2>/dev/null; then
  log "нет интернета на Mac; проверка пропущена"
  exit 0
fi
check survey 'Опрос' survey_alive
check llm 'ИИ-модель интервьюера' llm_alive
exit 0

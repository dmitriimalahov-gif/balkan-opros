#!/bin/bash
# Автозапуск только синхронизации кода с GitHub; опрос и туннель на Mac не запускаются.
set -euo pipefail
BASE=/Users/brandbox/erp2-inbox/process-survey
LABEL=com.balkan.process-survey-code-sync
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
SERVICE="gui/$UID/$LABEL"

case "${1:-install}" in
  install)
    mkdir -p "$HOME/Library/LaunchAgents" "$BASE/run"
    cp "$BASE/launchd/$LABEL.plist" "$PLIST"
    chmod 644 "$PLIST"
    launchctl bootout "$SERVICE" 2>/dev/null || true
    launchctl enable "$SERVICE"
    launchctl bootstrap "gui/$UID" "$PLIST"
    echo "Автосинхронизация кода включена: каждые 2 минуты, журнал $BASE/run/code-sync.log"
    ;;
  stop|remove)
    launchctl bootout "$SERVICE" 2>/dev/null || true
    launchctl disable "$SERVICE" 2>/dev/null || true
    echo "Автосинхронизация кода отключена; опрос и его данные не изменены"
    ;;
  status)
    launchctl print "$SERVICE"
    ;;
  *)
    echo "Использование: $0 [install|stop|status]" >&2
    exit 1
    ;;
esac

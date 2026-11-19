#!/bin/bash
# Автозапуск сторожа постоянного сервера (опрос + ИИ-модель); уведомления на Mac при сбое и восстановлении.
set -euo pipefail
BASE=/Users/brandbox/erp2-inbox/process-survey
LABEL=com.balkan.process-survey-server-monitor
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
    echo "Сторож сервера включён: каждые 5 минут, журнал $BASE/run/server-monitor.log"
    ;;
  stop|remove)
    launchctl bootout "$SERVICE" 2>/dev/null || true
    launchctl disable "$SERVICE" 2>/dev/null || true
    echo "Сторож сервера отключён"
    ;;
  status)
    launchctl print "$SERVICE"
    ;;
  *)
    echo "Использование: $0 [install|stop|status]" >&2
    exit 1
    ;;
esac

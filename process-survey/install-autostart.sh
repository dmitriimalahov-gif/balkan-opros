#!/bin/bash
# Автозапуск опроса после перезагрузки Mac (LaunchAgent пользователя). Запускать вручную, по желанию.
#   ./install-autostart.sh          — включить
#   ./install-autostart.sh remove   — выключить
set -euo pipefail
LABEL=com.balkan.process-survey
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
BASE=/Users/brandbox/erp2-inbox/process-survey
if [[ "${1:-}" == remove ]]; then
  launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
  rm -f "$PLIST"; echo "автозапуск выключен"; exit 0
fi
cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key><array><string>/bin/bash</string><string>$BASE/start.sh</string><string>start</string></array>
  <key>RunAtLoad</key><true/>
  <key>AbandonProcessGroup</key><true/>
  <key>WorkingDirectory</key><string>$BASE/run</string>
  <key>StandardOutPath</key><string>$BASE/run/autostart.log</string>
  <key>StandardErrorPath</key><string>$BASE/run/autostart.log</string>
</dict>
</plist>
EOF
launchctl bootstrap "gui/$(id -u)" "$PLIST" 2>/dev/null || launchctl kickstart -k "gui/$(id -u)/$LABEL"
echo "автозапуск включён: $PLIST"

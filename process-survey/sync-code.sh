#!/bin/bash
# Синхронизация исходного кода с GitHub без паролей, данных сотрудников и рабочих файлов.
# Запускается отдельным LaunchAgent раз в 2 минуты; можно запустить вручную: ./sync-code.sh
set -euo pipefail
export PATH='/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin'

BASE="${SURVEY_BASE:-/Users/brandbox/Desktop/BALCAN/process-survey}"
REPO="${SURVEY_PAGES:-/Users/brandbox/erp2-inbox/process-survey/pages}"
DEST="$REPO/process-survey"
PY="${SURVEY_PYTHON:-/Library/Frameworks/Python.framework/Versions/3.12/bin/python3}"
RUN="$BASE/run"
LOCK="$RUN/code-sync.lock"

[[ -d "$REPO/.git" ]] || exit 0
mkdir -p "$RUN" "$DEST"
# Не допускаем двух одновременных синхронизаций.
if ! mkdir "$LOCK" 2>/dev/null; then
  exit 0
fi
trap 'rmdir "$LOCK" 2>/dev/null || true' EXIT

cd "$REPO"
git fetch -q origin main

# Сначала безопасно объединяем внешние обновления GitHub. При конфликте ничего не публикуем.
if [[ "$(git rev-parse HEAD)" != "$(git rev-parse origin/main)" ]] && ! git merge-base --is-ancestor origin/main HEAD; then
  if [[ -n "$(git status --porcelain)" ]]; then
    echo "$(date '+%F %T') ветка требует объединения; локальные изменения сохранены" >&2
    exit 1
  fi
  if ! git merge --no-edit origin/main; then
    git merge --abort 2>/dev/null || true
    echo "$(date '+%F %T') конфликт веток; автоматическая публикация остановлена" >&2
    exit 1
  fi
fi

# Собранная страница всегда соответствует исходнику интерфейса.
"$PY" "$BASE/build_index.py" "$BASE/source/karta-processov.artifact.html"

# --delete удаляет из копии только исходники, удалённые из проекта. Исключённые каталоги
# не переносятся и не удаляются; вложения и данные сотрудников сюда никогда не попадают.
/usr/bin/rsync -a --delete \
  --exclude='.DS_Store' \
  --exclude='__pycache__/' \
  --exclude='*.py[cod]' \
  --exclude='node_modules/' \
  --exclude='.env' \
  --exclude='*.env' \
  --exclude='ADMIN_PASSWORD.txt' \
  --exclude='data/' \
  --exclude='exports/' \
  --exclude='pages/' \
  --include='run/.gitkeep' \
  --exclude='run/*' \
  "$BASE/" "$DEST/"

if [[ -n "$(git status --porcelain -- process-survey)" ]]; then
  echo "$(date '+%F %T') изменения кода: запускаю тесты"
  (
    cd "$DEST"
    "$PY" -m unittest discover -q
    "$PY" -m unittest discover -s tests -q
  )
  git add -A -- process-survey

  # Последний барьер перед коммитом: запрещённые пути и характерные секреты не публикуем.
  while IFS= read -r file; do
    case "$file" in
      *ADMIN_PASSWORD.txt|*.env|*/data/*|*/exports/*|*/run/*)
        if [[ "$file" != 'process-survey/run/.gitkeep' ]]; then
          echo "$(date '+%F %T') запрещённый файл в коммите: $file" >&2
          exit 1
        fi
        ;;
    esac
  done < <(git diff --cached --name-only -- process-survey)
  secret_pattern='sk-''strata-|gho_''[A-Za-z0-9]+|github_pat_''|BEGIN (RSA |OPENSSH |EC )?PRIVATE KEY'
  if git diff --cached -- process-survey | grep -Eq "$secret_pattern"; then
    echo "$(date '+%F %T') возможный секрет в изменениях; коммит остановлен" >&2
    exit 1
  fi

  if ! git diff --cached --quiet -- process-survey; then
    git -c user.name='dmitriimalahov-gif' -c user.email='dmitrii.malahov@gmail.com' \
      commit -q -m 'Синхронизация кода опроса' -- process-survey
  fi
fi

# Отправляем также ранее созданный коммит после временного сбоя сети.
if [[ "$(git rev-parse HEAD)" != "$(git rev-parse origin/main)" ]]; then
  git push -q origin main
  echo "$(date '+%F %T') код опубликован: $(git rev-parse --short HEAD)"
else
  echo "$(date '+%F %T') изменений кода нет"
fi

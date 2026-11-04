#!/usr/bin/env bash
# Replaces the planny database with a dump made by backup.sh, then starts the services again.
#
# The dump is first restored in full into a separate database while the services keep running,
# because pg_restore --list reads only the table of contents and misses a damaged file. The
# current database is replaced after that, and it comes back if the services then fail to start.
#
# Usage: restore.sh <dump-file> [--yes]
# Environment: PLANNY_ENV (dev or prod, default dev).
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
DEPLOY_DIR="$(cd -- "$SCRIPT_DIR/.." && pwd)"
COMPOSE=(docker compose --project-directory "$DEPLOY_DIR"
  -f "$DEPLOY_DIR/compose.yaml" -f "$DEPLOY_DIR/compose.${PLANNY_ENV:-dev}.yaml")
LIVE_DB=planny
TRIAL_DB=planny_restore
PREVIOUS_DB=planny_replaced

die() {
  echo "ошибка: $*" >&2
  exit 1
}

step() {
  echo "==> $*"
}

# stdin is closed so that docker does not swallow the operator's answer to the prompt.
db() {
  "${COMPOSE[@]}" exec -T db "$@" < /dev/null
}

drop_database() {
  "${COMPOSE[@]}" exec -T -e PGOPTIONS='-c client_min_messages=warning' db \
    dropdb -U planny --maintenance-db=postgres --force --if-exists "$1" < /dev/null
}

# Renames $1 to $2 and $3 to $4 in one transaction, so a failure leaves both names as they were.
rename_databases() {
  db psql -U planny -d postgres -q -v ON_ERROR_STOP=1 -1 \
    -c "ALTER DATABASE $1 RENAME TO $2" \
    -c "ALTER DATABASE $3 RENAME TO $4"
}

on_error() {
  echo "Восстановление прервано, база $LIVE_DB не изменена." >&2
  echo "api, worker и bff могли остаться остановленными. Исправьте причину и запустите restore.sh снова." >&2
}

[[ $# -ge 1 && $# -le 2 ]] || die "использование: restore.sh <файл-копии> [--yes]"
[[ $# -eq 1 || "$2" == "--yes" ]] || die "неизвестный аргумент: $2"
DUMP="$1"
ASSUME_YES=false
if [[ $# -eq 2 ]]; then
  ASSUME_YES=true
fi

[[ -f "$DUMP" ]] || die "файл не найден: $DUMP"

step "Запуск db, если он не запущен"
"${COMPOSE[@]}" up -d --wait db

if [[ -n "$(db psql -U planny -d postgres -Atc "SELECT 1 FROM pg_database WHERE datname = '$PREVIOUS_DB'")" ]]; then
  die "база $PREVIOUS_DB осталась от прерванного восстановления. Проверьте её и удалите вручную"
fi

step "Пробное восстановление из $DUMP, сервисы продолжают работать"
drop_database "$TRIAL_DB"
db createdb -U planny --maintenance-db=postgres "$TRIAL_DB"
if ! "${COMPOSE[@]}" exec -T db pg_restore -U planny -d "$TRIAL_DB" --no-owner --exit-on-error < "$DUMP"; then
  drop_database "$TRIAL_DB"
  die "копия повреждена или это не pg_dump: $DUMP. База $LIVE_DB не тронута"
fi
if ! users="$(db psql -U planny -d "$TRIAL_DB" -Atc 'SELECT count(*) FROM app_user')"; then
  drop_database "$TRIAL_DB"
  die "в копии нет данных Planny: $DUMP. База $LIVE_DB не тронута"
fi
echo "Копия читается полностью, пользователей в ней: $users"

if [[ "$ASSUME_YES" == false ]]; then
  echo "Текущая база $LIVE_DB будет заменена содержимым файла $DUMP."
  echo "Чтобы продолжить, введите restore:"
  answer=""
  read -r answer || true
  if [[ "$answer" != "restore" ]]; then
    drop_database "$TRIAL_DB"
    echo "Отменено. База не изменена."
    exit 1
  fi
fi

trap on_error ERR

step "Остановка api, worker и bff"
"${COMPOSE[@]}" stop api worker bff

step "Подмена базы"
rename_databases "$LIVE_DB" "$PREVIOUS_DB" "$TRIAL_DB" "$LIVE_DB"

trap - ERR

# migrate runs first through depends_on, so an older dump is brought up to the current schema.
step "Запуск api, worker и bff (сначала выполнится migrate)"
if ! "${COMPOSE[@]}" up -d --wait api worker bff; then
  step "Сервисы не запустились на этой копии, возвращаю прежнюю базу"
  "${COMPOSE[@]}" stop api worker bff
  rename_databases "$LIVE_DB" "$TRIAL_DB" "$PREVIOUS_DB" "$LIVE_DB"
  drop_database "$TRIAL_DB"
  "${COMPOSE[@]}" up -d --wait api worker bff \
    || die "прежняя база возвращена, но сервисы не запустились. Смотрите логи"
  die "восстановление отменено, работает прежняя база. Причину смотрите в логах migrate и api"
fi

step "Удаление прежней базы"
drop_database "$PREVIOUS_DB"

echo "Восстановление завершено."

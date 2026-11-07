#!/usr/bin/env bash
# Restores a real dump into a throwaway project and reads it with the current images: the proof
# that a copy comes back, which backup.sh cannot give because pg_restore --list reads only the
# table of contents. It never touches the live project: the name planny-trial is fixed here, there
# are no published ports and no networks outside the project, and the project is removed on exit.
#
# The run goes through the same steps as an update over restored data: pg_restore into an empty
# database, alembic upgrade head of the current release, alembic check, and a read of the users
# through the ORM.
#
# Usage: trial-restore.sh [dump-file]
# Without an argument the newest planny-*.dump in BACKUP_DIR (default deploy/backup/dumps) is used,
# and it must be younger than TRIAL_MAX_AGE_HOURS (default 48), otherwise the run still restores it
# but exits with an error: the backup timer looks broken. The server runs this weekly from
# planny-trial-restore.timer, see `make trial-restore` for the dev machine.
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
DEPLOY_DIR="$(cd -- "$SCRIPT_DIR/.." && pwd)"
PROJECT=planny-trial
# The project name and the file list come only from this script, never from the environment, so
# `down -v` below cannot reach the live project.
unset COMPOSE_PROJECT_NAME COMPOSE_FILE COMPOSE_PROFILES
COMPOSE=(docker compose -p "$PROJECT" --project-directory "$DEPLOY_DIR"
  -f "$DEPLOY_DIR/compose.yaml")
stale=""

die() {
  echo "ошибка: $*" >&2
  exit 1
}

step() {
  echo "==> $*"
}

teardown() {
  "${COMPOSE[@]}" down -v --remove-orphans > /dev/null 2>&1 || true
}

# The trial project is removed on any exit: success, failed step, or a signal.
trap teardown EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

# stdin is closed so that docker does not read the rest of the script or the terminal.
db() {
  "${COMPOSE[@]}" exec -T db "$@" < /dev/null
}

migrate() {
  "${COMPOSE[@]}" run --rm -T --no-deps migrate "$@" < /dev/null
}

[[ $# -le 1 ]] || die "использование: trial-restore.sh [файл-копии]"
MAX_AGE_HOURS="${TRIAL_MAX_AGE_HOURS:-48}"
[[ "$MAX_AGE_HOURS" =~ ^[1-9][0-9]*$ ]] \
  || die "TRIAL_MAX_AGE_HOURS должно быть целым числом больше нуля, получено: $MAX_AGE_HOURS"

if [[ $# -eq 1 ]]; then
  DUMP="$1"
  [[ -f "$DUMP" ]] || die "файл не найден: $DUMP"
else
  DUMP_DIR="${BACKUP_DIR:-$DEPLOY_DIR/backup/dumps}"
  [[ -d "$DUMP_DIR" ]] || die "папка с копиями не найдена: $DUMP_DIR"
  # sed instead of head: head closes the pipe early and pipefail would report that as a failure.
  DUMP="$(find "$DUMP_DIR" -maxdepth 1 -type f -name 'planny-*.dump' -printf '%T@ %p\n' \
    | sort -rn | sed -n '1s/^[^ ]* //p')"
  [[ -n "$DUMP" ]] || die "в $DUMP_DIR нет файлов planny-*.dump"
fi

size="$(du -h -- "$DUMP" | cut -f1)"
age_seconds=$(($(date +%s) - $(stat -c %Y -- "$DUMP")))
age="$((age_seconds / 3600)) ч $((age_seconds % 3600 / 60)) мин"
if [[ $# -eq 0 && "$age_seconds" -gt $((MAX_AGE_HOURS * 3600)) ]]; then
  stale="самой свежей копии $age, а допустимо $MAX_AGE_HOURS ч: таймер planny-backup, похоже, не работает"
  echo "ошибка: $stale" >&2
fi

if [[ -n "$(docker ps -aq --filter "label=com.docker.compose.project=$PROJECT")" \
  || -n "$(docker volume ls -q --filter "label=com.docker.compose.project=$PROJECT")" ]]; then
  step "Остатки прерванного запуска $PROJECT, удаляю"
  teardown
fi

step "Пустая база в проекте $PROJECT"
"${COMPOSE[@]}" up -d --wait db
# The server of the first start can answer through the socket while it still initializes, and
# the final one listens on TCP.
ready=false
for _ in $(seq 1 30); do
  if db pg_isready -q -h 127.0.0.1 -U planny -d planny; then
    ready=true
    break
  fi
  sleep 2
done
[[ "$ready" == true ]] || die "db не стала доступна по сети контейнера"

step "Восстановление $DUMP"
"${COMPOSE[@]}" exec -T db pg_restore -U planny -d planny --no-owner --exit-on-error < "$DUMP" \
  || die "копия не восстанавливается: $DUMP"
users="$(db psql -U planny -d planny -Atc 'SELECT count(*) FROM app_user')" \
  || die "в копии нет данных Planny: $DUMP"

step "alembic upgrade head поверх восстановленных данных"
migrate || die "миграции текущей версии не применились к копии"

step "alembic check"
migrate alembic check || die "схема после миграций расходится с моделями"

# The output holds logins, so only the number of rows is kept.
step "Чтение пользователей через ORM"
listed="$(migrate planny users list | wc -l)" || die "planny users list не прочитал данные"
[[ "$listed" -eq "$users" ]] || die "ORM прочитал $listed пользователей, в базе их $users"

revision="$(migrate alembic current 2> /dev/null | tail -n 1)" || die "alembic current не ответил"

echo
echo "Файл:          $DUMP"
echo "Размер:        $size"
echo "Возраст:       $age"
echo "Пользователей: $users"
echo "Ревизия:       $revision"
if [[ -n "$stale" ]]; then
  echo "Результат:     копия восстановилась, но она устарела" >&2
  die "$stale"
fi
echo "Результат:     проверка пройдена"

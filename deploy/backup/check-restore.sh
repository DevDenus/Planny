#!/usr/bin/env bash
# The whole path of a backup on a throwaway stack: a damaged copy changes nothing, a good copy
# brings the data and the logins back, on the running database and on a clean one. It runs in the
# e2e project, so the data of the dev stack is never touched.
#
# Usage: check-restore.sh. See `make restore-check`.
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
DEPLOY_DIR="$(cd -- "$SCRIPT_DIR/.." && pwd)"
export PLANNY_ENV=e2e
# Wins over the name in compose.e2e.yaml and over the shell, and restore.sh inherits it. `down -v`
# below may delete only this project's volume, and `make e2e` can have its own running.
export COMPOSE_PROJECT_NAME=planny-restore-check
COMPOSE=(docker compose --project-directory "$DEPLOY_DIR"
  -f "$DEPLOY_DIR/compose.yaml" -f "$DEPLOY_DIR/compose.e2e.yaml")
BFF=http://127.0.0.1:18080
LOGIN=restore-check
PASSWORD=restore-check-password
WORK="$(mktemp -d)"
JAR="$WORK/cookies"

cleanup() {
  "${COMPOSE[@]}" down -v --remove-orphans > /dev/null 2>&1 || true
  rm -rf -- "$WORK"
}
trap cleanup EXIT

fail() {
  echo "ПРОВАЛ: $*" >&2
  exit 1
}

step() {
  echo "==> $*"
}

sql() {
  "${COMPOSE[@]}" exec -T db psql -U planny -d "${2:-planny}" -Atc "$1" < /dev/null
}

# Rows that only people change: the sessions and the audit move on by themselves.
fingerprint() {
  sql "SELECT md5(string_agg(row, ',' ORDER BY row)) FROM (
         SELECT id::text || title || version AS row FROM task
         UNION ALL SELECT id::text || login || password_hash FROM app_user
       ) AS rows"
}

csrf() {
  awk '$6 == "planny_csrf" { print $7 }' "$JAR"
}

api() {
  curl -sS -f -o /dev/null -b "$JAR" -c "$JAR" -H 'content-type: application/json' \
    -H "X-CSRF-Token: $(csrf)" "$@"
}

sign_in() {
  rm -f -- "$JAR"
  curl -sS -f -o /dev/null -c "$JAR" -H 'content-type: application/json' \
    -d "{\"login\":\"$LOGIN\",\"password\":\"$1\"}" "$BFF/bff/login"
}

services_answer() {
  curl -sS -f -o /dev/null "$BFF/" && curl -sS -f -o /dev/null -b "$JAR" "$BFF/bff/api/v1/me"
}

leftovers() {
  sql "SELECT count(*) FROM pg_database WHERE datname IN ('planny_restore', 'planny_replaced')" postgres
}

step "Стек и данные"
"${COMPOSE[@]}" up -d --build --wait > /dev/null 2>&1
one_time="$("${COMPOSE[@]}" exec -T api planny users create "$LOGIN" --name Проверка \
  | sed -n 's/^Одноразовый пароль: //p')"
[[ -n "$one_time" ]] || fail "CLI не выдал пароль"
sign_in "$one_time"
api -d "{\"current_password\":\"$one_time\",\"new_password\":\"$PASSWORD\"}" \
  "$BFF/bff/api/v1/auth/change-password"
api -d '{"title":"Задача из копии"}' "$BFF/bff/api/v1/tasks"
saved="$(fingerprint)"

step "Копия"
"$SCRIPT_DIR/backup.sh" "$WORK/copies" > /dev/null
dump="$(find "$WORK/copies" -name 'planny-*.dump')"
[[ -s "$dump" ]] || fail "копия не появилась"
[[ "$(stat -c '%a' "$dump")" == 600 ]] || fail "у копии не права 600"
size="$(stat -c '%s' "$dump")"

api -d '{"title":"Задача после копии"}' "$BFF/bff/api/v1/tasks"
changed="$(fingerprint)"
[[ "$changed" != "$saved" ]] || fail "изменение не видно в отпечатке"

# A copy of the dump with `count` bytes of noise at this share of its size, in percent.
damaged() {
  local percent="$1" count="$2" file="$WORK/noise-$1"
  cp -- "$dump" "$file"
  dd if=/dev/urandom of="$file" bs=1 seek=$((size * percent / 100)) count="$count" conv=notrunc \
    status=none
  echo "$file"
}

head -c $((size / 2)) -- "$dump" > "$WORK/truncated"
head -c 4096 /dev/urandom > "$WORK/garbage"
: > "$WORK/empty"
echo 'SELECT 1;' > "$WORK/not-a-dump"

for file in "$WORK/truncated" "$WORK/garbage" "$WORK/empty" "$WORK/not-a-dump" \
  "$(damaged 25 256)" "$(damaged 50 256)" "$(damaged 75 256)"; do
  step "Повреждённая копия: $(basename -- "$file")"
  if "$SCRIPT_DIR/restore.sh" "$file" --yes > "$WORK/restore.log" 2>&1; then
    cat "$WORK/restore.log"
    fail "restore.sh принял повреждённую копию $(basename -- "$file")"
  fi
  grep -q 'не тронута' "$WORK/restore.log" || { cat "$WORK/restore.log"; fail "отказ по другой причине"; }
  [[ "$(fingerprint)" == "$changed" ]] || fail "повреждённая копия изменила базу"
  [[ "$(leftovers)" == 0 ]] || fail "остались служебные базы"
  services_answer || fail "сервисы перестали отвечать"
done

step "Отказ на вопросе оставляет всё как было"
if echo no | "$SCRIPT_DIR/restore.sh" "$dump" > /dev/null 2>&1; then
  fail "restore.sh продолжил без подтверждения"
fi
[[ "$(fingerprint)" == "$changed" ]] || fail "отказ изменил базу"
[[ "$(leftovers)" == 0 ]] || fail "остались служебные базы"

step "Хорошая копия на работающей базе"
"$SCRIPT_DIR/restore.sh" "$dump" --yes > /dev/null 2>&1
[[ "$(fingerprint)" == "$saved" ]] || fail "данные не совпали с копией"
[[ "$(leftovers)" == 0 ]] || fail "остались служебные базы"
sign_in "$PASSWORD"
services_answer || fail "сервисы не отвечают после восстановления"

step "Хорошая копия на чистой базе"
"${COMPOSE[@]}" down -v > /dev/null 2>&1
"$SCRIPT_DIR/restore.sh" "$dump" --yes > /dev/null 2>&1
[[ "$(fingerprint)" == "$saved" ]] || fail "данные не совпали с копией"
sign_in "$PASSWORD"
services_answer || fail "сервисы не отвечают после восстановления"

echo "Проверка пройдена."

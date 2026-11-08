#!/usr/bin/env bash
# Installs a release bundle made by deploy/release.sh on the server. Run it from the extracted
# bundle: tar -xf /tmp/planny-<version>.tar -C /tmp && sudo /tmp/planny-<version>/deploy/server/update.sh
#
# Order: checks, load images, backup, stop api/worker/bff, switch the version, start with migrate.
# If the new version does not come up, the previous version runs again on the pre-update backup.
# Data written between the backup and the failure is lost, so the backup is taken right before.
#
# Layout under PLANNY_ROOT:
#   .env                  secrets and PLANNY_VERSION, mode 600, never overwritten once it exists
#   releases/<version>/   the bundle without images.tar.gz; deploy/.env is a symlink to ../../../.env
#   current               symlink to releases/<version>
#   logs/                 one log per run
#
# Usage: update.sh [--yes] [--reinstall]
# --yes skips the confirmation prompt. By default the version that is already current is refused:
# docker load would overwrite that version's images, and a rollback would have nothing to return
# to. --reinstall allows it: a failed reinstall rolls the database back to the pre-update copy, but
# the images stay the new ones.
# Environment: PLANNY_ROOT (default /opt/planny), PLANNY_SKIP_SYSTEMD=1 (no root, no systemd units;
# for testing). COMPOSE_PROJECT_NAME is honoured when exported; -p is never passed.
# Exit codes: 0 done, 1 failed (rolled back or nothing changed), 2 .env created or invalid,
# 3 rollback failed.
set -euo pipefail
umask 022

BUNDLE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
PLANNY_ROOT="${PLANNY_ROOT:-/opt/planny}"
ENV_FILE="$PLANNY_ROOT/.env"
RELEASES="$PLANNY_ROOT/releases"
CURRENT="$PLANNY_ROOT/current"
MIN_COMPOSE=2.24.0
KEEP_RELEASES=3
ASSUME_YES=false
REINSTALL=false

VERSION=""
PREV_VERSION=""
PREV_RELEASE=""
RELEASE=""
NEW_TMP=""
DUMP=""
LOG=""
# none: nothing changed; stopped: api/worker/bff are stopped; switched: .env and current name the
# new version; finished: the new version runs. The EXIT trap rolls back from stopped and switched.
STATE=none
COMPOSE_NEW=()
COMPOSE_PREV=()
declare -A ENV_VALUES

die() {
  echo "ошибка: $*" >&2
  exit 1
}

# An unusable .env is exit code 2, so that the operator can tell it from a failed update.
die_env() {
  echo "ошибка: $*" >&2
  exit 2
}

step() {
  echo "==> $*"
}

warn() {
  echo "предупреждение: $*" >&2
}

# Parses KEY=VALUE lines into ENV_VALUES without executing anything.
load_env() {
  local line key value
  ENV_VALUES=()
  while IFS= read -r line || [[ -n "$line" ]]; do
    line="${line%$'\r'}"
    if [[ "$line" =~ ^[[:space:]]*(#.*)?$ ]]; then
      continue
    fi
    [[ "$line" =~ ^([A-Za-z_][A-Za-z0-9_]*)=(.*)$ ]] \
      || die_env "$ENV_FILE: строка не в формате KEY=VALUE: $line"
    key="${BASH_REMATCH[1]}"
    value="${BASH_REMATCH[2]}"
    if [[ "$value" =~ ^\"(.*)\"$ || "$value" =~ ^\'(.*)\'$ ]]; then
      value="${BASH_REMATCH[1]}"
    else
      value="${value%%[[:space:]]#*}"
      value="${value%"${value##*[![:space:]]}"}"
    fi
    ENV_VALUES["$key"]="$value"
  done < "$ENV_FILE"
}

write_env_template() {
  (
    umask 077
    {
      echo "# Created by deploy/server/update.sh on $(date -u +%Y-%m-%dT%H:%M:%SZ). Never overwritten."
      echo
      echo "# Database password. Hex only: the value goes into a database URL unescaped."
      echo "POSTGRES_PASSWORD=$(openssl rand -hex 32)"
      echo
      echo "# Shared secret between the BFF and the API."
      echo "BFF_SHARED_SECRET=$(openssl rand -hex 32)"
      echo
      echo "# Key that signs session cookies."
      echo "COOKIE_KEY=$(openssl rand -base64 32 | tr '+/' '-_')"
      echo
      echo "# The server runs behind HTTPS, so cookies are secure."
      echo "COOKIE_SECURE=true"
      echo
      echo "# Caddy writes the real client address to X-Forwarded-For."
      echo "TRUST_FORWARDED_FOR=true"
      echo
      echo "# LAN address of this server: the API port is published on it only. Fill it in."
      echo "LAN_IP="
      echo
      echo "# The release that runs. Written by update.sh, do not edit."
      echo "PLANNY_VERSION="
      echo
      echo "# Where backups go: a directory on the second disk."
      echo "BACKUP_DIR=/mnt/hdd2/planny-backups"
      echo
      echo "# Mount point of the second disk: no backup is written while it is not mounted."
      echo "BACKUP_MOUNT=/mnt/hdd2"
      echo
      echo "# Backups older than this many days are deleted after a new one succeeds."
      echo "BACKUP_KEEP_DAYS=14"
    } > "$ENV_FILE"
  )
}

# Replaces every PLANNY_VERSION line (or appends one), keeping the rest of the file as it is.
set_env_version() {
  local tmp
  tmp="$(mktemp "$PLANNY_ROOT/.env.XXXXXX")"
  if ! awk -v value="$1" '
      /^PLANNY_VERSION=/ { print "PLANNY_VERSION=" value; seen = 1; next }
      { print }
      END { if (!seen) print "PLANNY_VERSION=" value }
    ' "$ENV_FILE" > "$tmp"; then
    rm -f -- "$tmp"
    return 1
  fi
  mv -- "$tmp" "$ENV_FILE"
}

# Points current at releases/<version> in one rename.
switch_current() {
  ln -sfn "releases/$1" "$PLANNY_ROOT/.current.new"
  mv -T -- "$PLANNY_ROOT/.current.new" "$CURRENT"
}

# Sets the array named by $1 to the compose command of a release. PLANNY_VERSION is passed
# explicitly, because .env holds the old value (or none) until the version is switched.
make_compose() {
  local -n target="$1"
  # shellcheck disable=SC2034  # the nameref writes the caller's array
  target=(env "PLANNY_VERSION=$3" docker compose --project-directory "$2/deploy"
    -f "$2/deploy/compose.yaml" -f "$2/deploy/compose.prod.yaml")
}

# Lists planny-*.dump files of a directory, sorted; nothing if the directory does not exist yet.
list_dumps() {
  if [[ -d "$1" ]]; then
    find "$1" -maxdepth 1 -type f -name 'planny-*.dump' | sort
  fi
}

version_lt() {
  [[ "$1" != "$2" && "$(printf '%s\n%s\n' "$1" "$2" | sort -V | head -n 1)" == "$1" ]]
}

confirm() {
  local answer=""
  echo "Обновление Planny: ${PREV_VERSION:-не установлено} -> $VERSION"
  printf 'Продолжить? [y/N] '
  read -r answer || true
  case "$answer" in
    y | Y | yes | да | Да | д | Д) ;;
    *)
      echo "Отменено, ничего не изменилось."
      exit 1
      ;;
  esac
}

print_failure_logs() {
  echo "--- логи migrate, api, bff (последние 50 строк) ---" >&2
  "${COMPOSE_NEW[@]}" logs --tail 50 migrate api bff >&2 || true
  echo "--- конец логов ---" >&2
}

# Runs from the EXIT trap, so any failure after the services were stopped ends up here too.
rollback() {
  local code="$1" restore_status
  STATE_AT_FAILURE="$STATE"
  trap '' INT TERM
  set +e
  echo "ошибка: обновление до $VERSION не удалось (код $code)." >&2

  if [[ "$STATE" == switched ]]; then
    print_failure_logs
  fi

  if [[ -z "$PREV_VERSION" ]]; then
    set_env_version ""
    rm -f -- "$CURRENT"
    echo "Это первая установка, откатываться некуда. Исправьте причину и запустите update.sh снова." >&2
    echo "Смотреть контейнеры: PLANNY_VERSION=$VERSION docker compose --project-directory $RELEASE/deploy -f $RELEASE/deploy/compose.yaml -f $RELEASE/deploy/compose.prod.yaml ps" >&2
    exit 1
  fi

  step "Возвращаю версию $PREV_VERSION"
  set_env_version "$PREV_VERSION"
  switch_current "$PREV_VERSION"

  if [[ "$STATE_AT_FAILURE" == stopped ]]; then
    # The database was not touched: it is enough to start the old services again.
    if "${COMPOSE_PREV[@]}" up -d --no-build --wait api worker bff; then
      echo "Версия $PREV_VERSION запущена снова, база не менялась." >&2
      exit 1
    fi
    DUMP_HINT="${DUMP:-<копия не снималась>}"
    echo "ОТКАТ НЕ УДАЛСЯ: сервисы версии $PREV_VERSION не запустились." >&2
    echo "Копия перед обновлением: $DUMP_HINT. Смотрите логи: docker compose --project-directory $PREV_RELEASE/deploy -f $PREV_RELEASE/deploy/compose.yaml -f $PREV_RELEASE/deploy/compose.prod.yaml logs" >&2
    exit 3
  fi

  if [[ -z "$DUMP" ]]; then
    echo "ОТКАТ НЕ УДАЛСЯ: перед обновлением копия не снималась (db не работала), восстанавливать нечего." >&2
    echo "Версия в $ENV_FILE и current возвращены на $PREV_VERSION. Запустите её вручную и проверьте базу:" >&2
    echo "  PLANNY_ENV=prod $PREV_RELEASE/deploy/backup/restore.sh <файл копии> --yes" >&2
    exit 3
  fi

  step "Восстанавливаю базу из $DUMP"
  env "PLANNY_VERSION=$PREV_VERSION" PLANNY_ENV=prod \
    "$PREV_RELEASE/deploy/backup/restore.sh" "$DUMP" --yes
  restore_status=$?
  if [[ $restore_status -ne 0 ]]; then
    echo "ОТКАТ НЕ УДАЛСЯ: restore.sh завершился с кодом $restore_status." >&2
    echo "Версия в $ENV_FILE и current возвращены на $PREV_VERSION. Восстановите базу вручную:" >&2
    echo "  sudo env PLANNY_VERSION=$PREV_VERSION PLANNY_ENV=prod $PREV_RELEASE/deploy/backup/restore.sh $DUMP --yes" >&2
    exit 3
  fi
  echo "Версия $PREV_VERSION работает на копии, снятой перед обновлением: $DUMP" >&2
  echo "Данные, внесённые после неё, потеряны. Причина в логах выше и в $LOG" >&2
  exit 1
}

on_exit() {
  local code=$?
  if [[ -n "$NEW_TMP" && -e "$NEW_TMP" ]]; then
    rm -rf -- "$NEW_TMP"
  fi
  if [[ "$STATE" == stopped || "$STATE" == switched ]]; then
    rollback "$code"
  fi
  return "$code"
}
trap on_exit EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

STATE_AT_FAILURE=""
DUMP_HINT=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --yes) ASSUME_YES=true ;;
    --reinstall) REINSTALL=true ;;
    *) die "использование: update.sh [--yes] [--reinstall]; неизвестный аргумент: $1" ;;
  esac
  shift
done

[[ "$PLANNY_ROOT" =~ ^/[A-Za-z0-9_./-]+$ ]] \
  || die "PLANNY_ROOT должен быть абсолютным путём из букв, цифр и _./-, получено: $PLANNY_ROOT"
[[ "${PLANNY_SKIP_SYSTEMD:-}" == 1 || $EUID -eq 0 ]] \
  || die "нужны права root: запустите через sudo"
[[ -f "$BUNDLE/VERSION" ]] || die "в $BUNDLE нет файла VERSION: запускайте update.sh из распакованного комплекта"
VERSION="$(< "$BUNDLE/VERSION")"
[[ "$VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || die "в VERSION не версия: $VERSION"
[[ "$BUNDLE/" != "$RELEASES/"* ]] || die "комплект лежит внутри $RELEASES, распакуйте его в другую папку, например /tmp"
for tool in docker flock ip sha256sum sort awk; do
  command -v "$tool" > /dev/null || die "не найдена команда $tool"
done

mkdir -p -- "$RELEASES" "$PLANNY_ROOT/logs"
exec 9> "$PLANNY_ROOT/.update.lock"
flock -n 9 || die "другое обновление уже идёт (замок $PLANNY_ROOT/.update.lock)"

LOG="$PLANNY_ROOT/logs/update-$VERSION-$(date -u +%Y%m%dT%H%M%SZ).log"
exec > >(tee -a "$LOG") 2>&1
echo "Журнал: $LOG"

RELEASE="$RELEASES/$VERSION"
if [[ -L "$CURRENT" ]]; then
  PREV_RELEASE="$(readlink -f -- "$CURRENT")"
  PREV_VERSION="$(basename -- "$PREV_RELEASE")"
fi

step "Проверка комплекта и сервера"
(cd -- "$BUNDLE" && sha256sum --quiet -c SHA256SUMS) || die "контрольные суммы комплекта не сошлись, распакуйте его заново"
for file in images.tar.gz deploy/compose.yaml deploy/compose.prod.yaml deploy/.env.example \
  deploy/backup/backup.sh deploy/backup/restore.sh; do
  [[ -f "$BUNDLE/$file" ]] || die "в комплекте нет файла $file"
done

compose_version="$(docker compose version --short)" || die "не найден плагин docker compose"
compose_version="${compose_version#v}"
compose_version="${compose_version%%[-+]*}"
[[ "$(printf '%s\n%s\n' "$MIN_COMPOSE" "$compose_version" | sort -V | head -n 1)" == "$MIN_COMPOSE" ]] \
  || die "нужен docker compose не старше $MIN_COMPOSE, установлен $compose_version"

if [[ ! -e "$ENV_FILE" ]]; then
  command -v openssl > /dev/null || die "не найдена команда openssl"
  write_env_template
  echo "Создан $ENV_FILE с новыми секретами (права 600)."
  echo "Впишите в него LAN_IP (адрес сервера в локальной сети), проверьте BACKUP_DIR и BACKUP_MOUNT и запустите update.sh снова."
  exit 2
fi

load_env
for key in POSTGRES_PASSWORD BFF_SHARED_SECRET COOKIE_KEY LAN_IP BACKUP_DIR; do
  [[ -n "${ENV_VALUES[$key]:-}" ]] || die_env "$ENV_FILE: не заполнена переменная $key"
done
for key in COOKIE_SECURE TRUST_FORWARDED_FOR; do
  [[ "${ENV_VALUES[$key]:-}" == true ]] || die_env "$ENV_FILE: на сервере $key должно быть true"
done
# Presence only: PLANNY_VERSION is empty before the first install. A key that is missing breaks the
# start through ${VAR:?} after the services are already stopped, so it is caught here.
while IFS= read -r key; do
  [[ -v "ENV_VALUES[$key]" ]] || die_env "$ENV_FILE: нет переменной $key из нового .env.example, добавьте её"
done < <(sed -n 's/^\([A-Za-z_][A-Za-z0-9_]*\)=.*/\1/p' "$BUNDLE/deploy/.env.example")
[[ "${ENV_VALUES[BACKUP_DIR]}" == /* ]] || die_env "$ENV_FILE: BACKUP_DIR должен быть абсолютным путём"

LAN_IP="${ENV_VALUES[LAN_IP]}"
local_addresses="$(ip -o addr show | awk '{ split($4, address, "/"); print address[1] }')"
grep -Fxq -- "$LAN_IP" <<< "$local_addresses" \
  || die_env "LAN_IP=$LAN_IP не назначен ни одному интерфейсу этого сервера (ip -o addr show)"

if [[ -n "$PREV_VERSION" ]]; then
  [[ -d "$PREV_RELEASE/deploy" ]] || die "current указывает на $PREV_RELEASE, там нет deploy"
  [[ "$PREV_VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || die "current указывает не на версию: $PREV_RELEASE"
  if version_lt "$VERSION" "$PREV_VERSION"; then
    die "установлена версия $PREV_VERSION, а в комплекте $VERSION. Понижать версию нельзя: откат — это восстановление копии (deploy/backup/restore.sh)"
  fi
  if [[ "$VERSION" == "$PREV_VERSION" ]]; then
    if [[ "$REINSTALL" == false ]]; then
      die "версия $VERSION уже установлена. docker load перезапишет её образы, и откатываться будет не на что. Соберите комплект с большим номером версии (или запустите с --reinstall, если понимаете последствия)"
    fi
    warn "переустановка $VERSION: образы этой версии будут перезаписаны новыми. Если переустановка не удастся, база вернётся к копии перед обновлением, но образы останутся новыми"
  fi
  make_compose COMPOSE_PREV "$PREV_RELEASE" "$PREV_VERSION"
fi
make_compose COMPOSE_NEW "$RELEASE" "$VERSION"

if [[ "$ASSUME_YES" == false ]]; then
  confirm
fi

step "Загрузка образов"
docker load -i "$BUNDLE/images.tar.gz"
host_arch="$(docker info -f '{{.Architecture}}')"
case "$host_arch" in
  x86_64) host_arch=amd64 ;;
  aarch64) host_arch=arm64 ;;
esac
for image in planny-backend planny-bff; do
  docker image inspect "$image:$VERSION" > /dev/null || die "после docker load нет образа $image:$VERSION"
  image_arch="$(docker image inspect -f '{{.Architecture}}' "$image:$VERSION")"
  [[ "$image_arch" == "$host_arch" ]] \
    || die "образ $image:$VERSION собран для $image_arch, а сервер $host_arch. Соберите комплект на машине той же архитектуры"
done

step "Сеть edge"
if ! docker network inspect edge > /dev/null 2>&1; then
  docker network create edge > /dev/null
  echo "Сеть edge создана."
fi

step "Установка releases/$VERSION"
NEW_TMP="$RELEASES/.new-$VERSION"
rm -rf -- "$NEW_TMP"
cp -a -- "$BUNDLE" "$NEW_TMP"
rm -f -- "$NEW_TMP/images.tar.gz"
ln -s -- "$ENV_FILE" "$NEW_TMP/deploy/.env"
rm -rf -- "$RELEASE"
mv -T -- "$NEW_TMP" "$RELEASE"
NEW_TMP=""

step "Обновление образа db (pull)"
"${COMPOSE_NEW[@]}" pull --quiet db || warn "не удалось обновить образ db, продолжаю с тем, что есть"

if [[ -n "$PREV_VERSION" ]] && [[ -n "$("${COMPOSE_PREV[@]}" ps --status running -q db)" ]]; then
  step "Копия базы перед обновлением"
  # The new dump is the one that did not exist before the run: file times can step with the clock.
  dumps_before="$(list_dumps "${ENV_VALUES[BACKUP_DIR]}")"
  backup_env=(env "PLANNY_VERSION=$PREV_VERSION" PLANNY_ENV=prod "BACKUP_DIR=${ENV_VALUES[BACKUP_DIR]}")
  for key in BACKUP_MOUNT BACKUP_KEEP_DAYS; do
    if [[ -n "${ENV_VALUES[$key]:-}" ]]; then
      backup_env+=("$key=${ENV_VALUES[$key]}")
    fi
  done
  if ! "${backup_env[@]}" "$RELEASE/deploy/backup/backup.sh"; then
    die "копия не снялась, обновление остановлено, ничего не изменилось"
  fi
  # backup.sh may delete expired dumps, so only the names that are new count.
  DUMP="$(comm -13 <(echo "$dumps_before") <(list_dumps "${ENV_VALUES[BACKUP_DIR]}") | tail -n 1)"
  [[ -n "$DUMP" ]] || die "backup.sh завершился успешно, но новой копии в ${ENV_VALUES[BACKUP_DIR]} нет. Обновление остановлено"
  echo "Копия: $DUMP"

  step "Остановка api, worker и bff"
  STATE=stopped
  "${COMPOSE_PREV[@]}" stop api worker bff
elif [[ -n "$PREV_VERSION" ]]; then
  warn "db версии $PREV_VERSION не запущена, копия перед обновлением не снимается"
fi

step "Переключение на версию $VERSION"
STATE=switched
set_env_version "$VERSION"
switch_current "$VERSION"

step "Запуск версии $VERSION (сначала выполнится migrate)"
"${COMPOSE_NEW[@]}" up -d --no-build --wait --wait-timeout 300 --remove-orphans db api worker bff
STATE=finished
echo "Версия $VERSION запущена."

systemd_ok=true
if [[ "${PLANNY_SKIP_SYSTEMD:-}" != 1 ]]; then
  step "Таймеры systemd"
  shopt -s nullglob
  units=("$RELEASE"/deploy/server/systemd/*)
  shopt -u nullglob
  if [[ ${#units[@]} -eq 0 ]]; then
    systemd_ok=false
    warn "в комплекте нет файлов systemd, таймеры резервных копий не установлены"
  else
    for unit in "${units[@]}"; do
      sed "s|@PLANNY_ROOT@|$PLANNY_ROOT|g" "$unit" > "/etc/systemd/system/$(basename -- "$unit")" || systemd_ok=false
    done
    systemctl daemon-reload || systemd_ok=false
    for unit in "${units[@]}"; do
      if [[ "$unit" == *.timer ]]; then
        systemctl enable --now "$(basename -- "$unit")" || systemd_ok=false
      fi
    done
    if [[ "$systemd_ok" == false ]]; then
      warn "таймеры systemd установились не полностью, проверьте systemctl list-timers 'planny-*'"
    fi
  fi
fi

step "Очистка старых версий"
mapfile -t versions < <(find "$RELEASES" -mindepth 1 -maxdepth 1 -type d -printf '%f\n' \
  | grep -E '^[0-9]+\.[0-9]+\.[0-9]+$' | sort -V)
declare -A keep=()
keep["$VERSION"]=1
if [[ -n "$PREV_VERSION" ]]; then
  keep["$PREV_VERSION"]=1
fi
for ((i = ${#versions[@]} - 1; i >= 0 && i >= ${#versions[@]} - KEEP_RELEASES; i--)); do
  keep["${versions[i]}"]=1
done
for old in "${versions[@]}"; do
  if [[ -z "${keep[$old]:-}" ]]; then
    echo "Удаляю версию $old"
    rm -rf -- "${RELEASES:?}/$old"
    docker image rm "planny-backend:$old" "planny-bff:$old" > /dev/null 2>&1 || true
  fi
done

step "Готово"
echo "Версия: $VERSION (до этого: ${PREV_VERSION:-не было})"
"${COMPOSE_NEW[@]}" ps
echo "Копия перед обновлением: ${DUMP:-не снималась}"
echo "Журнал: $LOG"
if [[ "$systemd_ok" == false ]]; then
  echo "ВНИМАНИЕ: таймеры systemd не установлены, см. предупреждение выше." >&2
fi

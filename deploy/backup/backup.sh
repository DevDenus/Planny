#!/usr/bin/env bash
# Writes a custom-format pg_dump of the planny database to a new file.
#
# Usage: backup.sh [target-dir]
# Environment: PLANNY_ENV (dev or prod, default dev), BACKUP_DIR, BACKUP_KEEP_DAYS (default 14),
# BACKUP_MOUNT. When BACKUP_MOUNT is set, it must be a mount point and the target directory must be
# inside it, so a missing second disk stops the backup instead of filling the system disk.
set -euo pipefail
umask 077

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
DEPLOY_DIR="$(cd -- "$SCRIPT_DIR/.." && pwd)"
COMPOSE=(docker compose --project-directory "$DEPLOY_DIR"
  -f "$DEPLOY_DIR/compose.yaml" -f "$DEPLOY_DIR/compose.${PLANNY_ENV:-dev}.yaml")
KEEP_DAYS="${BACKUP_KEEP_DAYS:-14}"
TARGET_DIR="${1:-${BACKUP_DIR:-$DEPLOY_DIR/backup/dumps}}"
tmp=""

die() {
  echo "ошибка: $*" >&2
  exit 1
}

# Removes the partial file on any exit: failed pg_dump, failed check, or a signal.
cleanup() {
  if [[ -n "$tmp" && -e "$tmp" ]]; then
    rm -f -- "$tmp"
  fi
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

[[ "$KEEP_DAYS" =~ ^[1-9][0-9]*$ ]] \
  || die "BACKUP_KEEP_DAYS должно быть целым числом больше нуля, получено: $KEEP_DAYS"

# Checked before anything is created: mkdir on an unmounted path would write to the system disk.
if [[ -n "${BACKUP_MOUNT:-}" ]]; then
  mountpoint -q -- "$BACKUP_MOUNT" \
    || die "$BACKUP_MOUNT не смонтирован, копия не сделана. Проверьте второй диск"
  mount_root="$(realpath -- "$BACKUP_MOUNT")"
  target_real="$(realpath -m -- "$TARGET_DIR")"
  [[ "$target_real/" == "${mount_root%/}/"* ]] \
    || die "папка копий $target_real не внутри $BACKUP_MOUNT, копия не сделана"
fi

mkdir -p -- "$TARGET_DIR"
TARGET_DIR="$(cd -- "$TARGET_DIR" && pwd)"
final="$TARGET_DIR/planny-$(date -u +%Y%m%d-%H%M%S).dump"
[[ ! -e "$final" ]] || die "файл уже существует: $final"
tmp="$final.tmp"

echo "Снимаю копию базы planny..."
"${COMPOSE[@]}" exec -T db pg_dump -U planny -d planny -Fc > "$tmp"

[[ -s "$tmp" ]] || die "pg_dump записал пустой файл"
"${COMPOSE[@]}" exec -T db pg_restore --list < "$tmp" > /dev/null \
  || die "pg_restore не читает новую копию"

mv -- "$tmp" "$final"
tmp=""
echo "Готово: $final ($(du -h -- "$final" | cut -f1))"

# Only after a valid new dump. The glob matches nothing but planny-*.dump files.
echo "Удаляю planny-*.dump старше $KEEP_DAYS дн.:"
find "$TARGET_DIR" -maxdepth 1 -type f -name 'planny-*.dump' \
  -mmin "+$((KEEP_DAYS * 1440))" -print -delete

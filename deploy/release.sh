#!/usr/bin/env bash
# Builds both images and packs them with the deploy files into dist/planny-<version>.tar.
#
# The tar is copied to the server and installed there by deploy/server/update.sh. The release is
# whatever is in the working tree: git is optional and only names the revision in REVISION and in
# the image labels (<sha>, plus -dirty when the tree has changes, or unknown without git).
#
# Usage: release.sh <version>   (for example 0.1.0)
# Environment: PLANNY_SERVER is the ssh host named in the printed next steps (default punkyserver).
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd -- "$SCRIPT_DIR/.." && pwd)"
SERVER="${PLANNY_SERVER:-punkyserver}"
# Files the server scripts rely on, relative to the repository root.
DEPLOY_FILES=(
  deploy/compose.yaml
  deploy/compose.prod.yaml
  deploy/.env.example
  deploy/backup/backup.sh
  deploy/backup/restore.sh
  deploy/backup/trial-restore.sh
  deploy/server/update.sh
)
stage=""

die() {
  echo "ошибка: $*" >&2
  exit 1
}

step() {
  echo "==> $*"
}

# Removes the half-packed staging directory on any exit.
cleanup() {
  if [[ -n "$stage" && -e "$stage" ]]; then
    rm -rf -- "$stage"
  fi
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

[[ $# -eq 1 ]] || die "использование: release.sh <версия>, например release.sh 0.1.0"
VERSION="$1"
[[ "$VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || die "версия должна выглядеть как 1.2.3, получено: $VERSION"

cd -- "$ROOT_DIR"
command -v docker > /dev/null || die "не найден docker"

# Informational only: a missing git or a directory that is not a repository is never an error.
REVISION=unknown
if command -v git > /dev/null && sha="$(git rev-parse HEAD 2> /dev/null)"; then
  REVISION="$sha"
  if [[ -n "$(git status --porcelain 2> /dev/null)" ]]; then
    REVISION="$REVISION-dirty"
  fi
fi
BUILT_AT="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

LABELS=(--label "org.opencontainers.image.version=$VERSION"
  --label "org.opencontainers.image.revision=$REVISION"
  --label "org.opencontainers.image.created=$BUILT_AT")

step "Сборка planny-backend:$VERSION"
docker build -t "planny-backend:$VERSION" "${LABELS[@]}" backend

step "Сборка planny-bff:$VERSION"
docker build -f bff/Dockerfile -t "planny-bff:$VERSION" "${LABELS[@]}" .

step "Сборка комплекта dist/planny-$VERSION.tar"
mkdir -p dist
stage="$ROOT_DIR/dist/planny-$VERSION"
rm -rf -- "$stage"
mkdir -p -- "$stage/deploy/backup" "$stage/deploy/server"

printf '%s\n' "$VERSION" > "$stage/VERSION"
printf '%s\n' "$REVISION" > "$stage/REVISION"
printf '%s\n' "$BUILT_AT" > "$stage/BUILT_AT"

for file in "${DEPLOY_FILES[@]}"; do
  [[ -f "$file" ]] || die "нет файла $file, комплект неполный"
  cp -p -- "$file" "$stage/$file"
done

# Whatever sits in deploy/server/systemd goes to the server: update.sh installs all of it.
shopt -s nullglob
units=(deploy/server/systemd/*)
shopt -u nullglob
[[ ${#units[@]} -gt 0 ]] || die "в deploy/server/systemd нет файлов, комплект неполный"
mkdir -p -- "$stage/deploy/server/systemd"
cp -p -- "${units[@]}" "$stage/deploy/server/systemd/"

step "Сохранение образов (docker save)"
docker save "planny-backend:$VERSION" "planny-bff:$VERSION" | gzip > "$stage/images.tar.gz"

step "Контрольные суммы"
(
  cd -- "$stage"
  sums="$(find . -type f -print0 | sort -z | xargs -0 sha256sum | sed 's|  \./|  |')"
  printf '%s\n' "$sums" > SHA256SUMS
)

tar_file="$ROOT_DIR/dist/planny-$VERSION.tar"
rm -f -- "$tar_file"
tar -cf "$tar_file" -C "$ROOT_DIR/dist" "planny-$VERSION"
rm -rf -- "$stage"
stage=""

echo
echo "Готово: $tar_file ($(du -h -- "$tar_file" | cut -f1)), ревизия $REVISION"
echo "Дальше:"
echo "  scp dist/planny-$VERSION.tar $SERVER:/tmp/"
echo "На сервере:"
echo "  tar -xf /tmp/planny-$VERSION.tar -C /tmp && sudo /tmp/planny-$VERSION/deploy/server/update.sh"

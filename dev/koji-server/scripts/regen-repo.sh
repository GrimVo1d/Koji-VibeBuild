#!/usr/bin/env bash
# Ручной триггер штатной задачи koji regen-repo для build-tag.
# Использует upstream createrepo_c из Fedora (входит в build-group, см. koji-init.sh).
# Идемпотентно: если задача уже бежит, koji вернёт её task-id без повторного запуска.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$(dirname "$SCRIPT_DIR")"

source .env

COMPOSE="${COMPOSE:-docker compose}"
if ! $COMPOSE version >/dev/null 2>&1; then
    if command -v podman >/dev/null 2>&1 && podman compose version >/dev/null 2>&1; then
        COMPOSE="podman compose"
    else
        echo "ERROR: neither '$COMPOSE' nor 'podman compose' is available"
        exit 1
    fi
fi

TAG="${1:-${KOJI_BUILD_TAG}}"

echo "==> koji regen-repo ${TAG}"
$COMPOSE exec -T koji-hub koji regen-repo "${TAG}" --wait
echo "==> repo for ${TAG} regenerated"

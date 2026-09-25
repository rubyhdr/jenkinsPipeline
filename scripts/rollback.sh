#!/usr/bin/env bash
# Manually roll an environment back to an earlier image.
#
#   scripts/rollback.sh production                          # previous image recorded by the last deploy
#   scripts/rollback.sh production localhost:5005/shelf:prod-1.0.4
#
# Needs SECRET_KEY and DB_PASSWORD, like deploy.sh.
set -euo pipefail

ENV_NAME="${1:?environment required}"
TARGET="${2:-}"
REPORT_DIR="${REPORT_DIR:-reports}"
: "${SECRET_KEY:?SECRET_KEY must be set}" "${DB_PASSWORD:?DB_PASSWORD must be set}"

if [[ -z "$TARGET" && -f "${REPORT_DIR}/${ENV_NAME}-previous-image.txt" ]]; then
  TARGET="$(cat "${REPORT_DIR}/${ENV_NAME}-previous-image.txt")"
fi
if [[ -z "$TARGET" ]]; then
  echo "No rollback target given and none recorded" >&2
  exit 1
fi

echo "==> Rolling ${ENV_NAME} back to ${TARGET}"
IMAGE="$TARGET" docker compose -p "shelf-${ENV_NAME}" -f "infra/docker-compose.${ENV_NAME}.yml" \
  up -d --wait --wait-timeout 180 app
docker inspect -f '{{.Config.Image}} {{.State.Health.Status}}' "library-${ENV_NAME}"

#!/usr/bin/env bash
# Deploy an image to an environment with health checks, smoke tests and automatic rollback.
#
#   scripts/deploy.sh <staging|production> <image> <expected-version>
#
# Requires SECRET_KEY and DB_PASSWORD in the environment (Jenkins injects them from credentials).
set -euo pipefail

ENV_NAME="${1:?environment required}"
NEW_IMAGE="${2:?image required}"
EXPECTED_VERSION="${3:?expected version required}"

COMPOSE_FILE="infra/docker-compose.${ENV_NAME}.yml"
PROJECT="shelf-${ENV_NAME}"
CONTAINER="library-${ENV_NAME}"
BASE_URL="http://${CONTAINER}:8000"
REPORT_DIR="${REPORT_DIR:-reports}"
mkdir -p "$REPORT_DIR"

compose() { docker compose -p "$PROJECT" -f "$COMPOSE_FILE" "$@"; }

PREVIOUS_IMAGE="$(docker inspect -f '{{.Config.Image}}' "$CONTAINER" 2>/dev/null || true)"
echo "${PREVIOUS_IMAGE}" > "${REPORT_DIR}/${ENV_NAME}-previous-image.txt"
echo "==> Deploying ${NEW_IMAGE} to ${ENV_NAME} (previous: ${PREVIOUS_IMAGE:-none})"

rollback() {
  echo "!!! Deployment to ${ENV_NAME} failed; rolling back"
  compose logs --tail 40 app || true
  if [[ -n "$PREVIOUS_IMAGE" && "$PREVIOUS_IMAGE" != "$NEW_IMAGE" ]]; then
    IMAGE="$PREVIOUS_IMAGE" compose up -d --wait --wait-timeout 180 app
    echo "<== Rolled back ${ENV_NAME} to ${PREVIOUS_IMAGE}"
    echo "rolled-back-to=${PREVIOUS_IMAGE}" > "${REPORT_DIR}/${ENV_NAME}-rollback.txt"
  else
    echo "No previous image to roll back to; stopping the broken release"
    compose stop app || true
  fi
}

if ! IMAGE="$NEW_IMAGE" compose up -d --wait --wait-timeout 180; then
  rollback
  exit 1
fi

if ! python3 scripts/smoke_test.py "$BASE_URL" --expect-version "$EXPECTED_VERSION" \
      --report "${REPORT_DIR}/${ENV_NAME}-smoke.json"; then
  rollback
  exit 1
fi

echo "==> ${ENV_NAME} is healthy on ${NEW_IMAGE}"

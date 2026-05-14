#!/usr/bin/env bash
# rollback.sh — Roll back to the previous Sonoro API deployment
#
# Usage:
#   ./infra/scripts/rollback.sh staging    <previous-image-tag>
#   ./infra/scripts/rollback.sh production <previous-image-tag>
#
# The previous image tag is printed by deploy.sh on success and stored in
# /etc/sonoro/last_deployed_<env> on the server.
#
# Required environment variables:
#   REGISTRY, SSH_HOST, SSH_USER, SSH_KEY_PATH (same as deploy.sh)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

TARGET="${1:?Usage: rollback.sh <staging|production> [image-tag]}"
REGISTRY="${REGISTRY:?REGISTRY env var must be set}"
SSH_HOST="${SSH_HOST:?SSH_HOST env var must be set}"
SSH_USER="${SSH_USER:-deploy}"
SSH_KEY_PATH="${SSH_KEY_PATH:-${HOME}/.ssh/id_rsa}"

SSH="ssh -i ${SSH_KEY_PATH} -o StrictHostKeyChecking=no ${SSH_USER}@${SSH_HOST}"

# Resolve which image to roll back to
if [[ -n "${2:-}" ]]; then
  ROLLBACK_IMAGE="${REGISTRY}/sonoro-api:${2}"
else
  # Try to read the previous tag stored during the last successful deploy
  ROLLBACK_IMAGE=$(${SSH} "cat /etc/sonoro/last_deployed_${TARGET} 2>/dev/null" || echo "")
  if [[ -z "${ROLLBACK_IMAGE}" ]]; then
    echo "❌ No previous image tag found. Pass it explicitly: rollback.sh ${TARGET} <image-tag>"
    exit 1
  fi
fi

if [[ "${TARGET}" == "production" ]]; then
  echo ""
  echo "⚠️  You are about to ROLL BACK PRODUCTION to: ${ROLLBACK_IMAGE}"
  read -rp "Type 'yes' to confirm: " CONFIRM
  if [[ "${CONFIRM}" != "yes" ]]; then
    echo "Aborted."
    exit 0
  fi
fi

echo "▶  Rolling back to: ${ROLLBACK_IMAGE}"

# Optional: downgrade one migration step before swapping containers
read -rp "Downgrade database one migration step? [y/N] " DOWNGRADE
if [[ "${DOWNGRADE}" =~ ^[Yy]$ ]]; then
  echo "▶  Downgrading database (alembic downgrade -1)"
  ${SSH} "docker run --rm \
    --env-file /etc/sonoro/.env.${TARGET} \
    ${ROLLBACK_IMAGE} \
    alembic downgrade -1"
fi

echo "▶  Swapping API container"
${SSH} "
  docker stop sonoro-${TARGET}-api 2>/dev/null || true
  docker rm   sonoro-${TARGET}-api 2>/dev/null || true
  docker run -d \
    --name sonoro-${TARGET}-api \
    --restart unless-stopped \
    --env-file /etc/sonoro/.env.${TARGET} \
    -p 8000:8000 \
    ${ROLLBACK_IMAGE}
"

echo "▶  Waiting for health check"
for i in {1..12}; do
  STATUS=$(${SSH} "curl -sf http://localhost:8000/api/v1/health | python3 -c \"import sys,json; print(json.load(sys.stdin).get('status',''))\" 2>/dev/null" || echo "")
  if [[ "${STATUS}" == "healthy" ]]; then
    echo "✅ Rollback successful — ${ROLLBACK_IMAGE}"
    exit 0
  fi
  echo "   waiting… (${i}/12)"
  sleep 5
done

echo "❌ Health check still failing after rollback. Manual intervention required."
exit 1

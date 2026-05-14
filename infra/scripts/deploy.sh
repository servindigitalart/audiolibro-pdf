#!/usr/bin/env bash
# deploy.sh — Build, push, and deploy Sonoro API
#
# Usage:
#   ./infra/scripts/deploy.sh staging    # Deploy to staging
#   ./infra/scripts/deploy.sh production # Deploy to production (requires confirmation)
#
# Required environment variables:
#   REGISTRY      — Container registry host (e.g. registry.digitalocean.com/sonoro)
#   SSH_HOST      — Deployment target hostname or IP
#   SSH_USER      — SSH user on the deployment target (default: deploy)
#   SSH_KEY_PATH  — Path to SSH private key (default: ~/.ssh/id_rsa)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

TARGET="${1:?Usage: deploy.sh <staging|production>}"
REGISTRY="${REGISTRY:?REGISTRY env var must be set}"
SSH_HOST="${SSH_HOST:?SSH_HOST env var must be set}"
SSH_USER="${SSH_USER:-deploy}"
SSH_KEY_PATH="${SSH_KEY_PATH:-${HOME}/.ssh/id_rsa}"

GIT_SHA="$(git -C "${REPO_ROOT}" rev-parse --short HEAD)"
IMAGE="${REGISTRY}/sonoro-api:${TARGET}-${GIT_SHA}"
LATEST="${REGISTRY}/sonoro-api:${TARGET}-latest"

if [[ "${TARGET}" == "production" ]]; then
  echo ""
  echo "⚠️  You are about to deploy to PRODUCTION."
  read -rp "Type 'yes' to confirm: " CONFIRM
  if [[ "${CONFIRM}" != "yes" ]]; then
    echo "Aborted."
    exit 0
  fi
fi

echo "▶  Building image: ${IMAGE}"
docker build \
  --file "${REPO_ROOT}/infra/docker/api.Dockerfile" \
  --target production \
  --tag "${IMAGE}" \
  --tag "${LATEST}" \
  "${REPO_ROOT}/services/api"

echo "▶  Pushing image to registry"
docker push "${IMAGE}"
docker push "${LATEST}"

SSH="ssh -i ${SSH_KEY_PATH} -o StrictHostKeyChecking=no ${SSH_USER}@${SSH_HOST}"

echo "▶  Pulling image on ${SSH_HOST}"
${SSH} "docker pull ${IMAGE}"

echo "▶  Running migrations"
${SSH} "docker run --rm \
  --env-file /etc/sonoro/.env.${TARGET} \
  ${IMAGE} \
  alembic upgrade head"

echo "▶  Restarting API service"
${SSH} "
  docker stop sonoro-${TARGET}-api 2>/dev/null || true
  docker rm   sonoro-${TARGET}-api 2>/dev/null || true
  docker run -d \
    --name sonoro-${TARGET}-api \
    --restart unless-stopped \
    --env-file /etc/sonoro/.env.${TARGET} \
    -p 8000:8000 \
    ${IMAGE}
"

echo "▶  Waiting for health check"
for i in {1..12}; do
  STATUS=$(${SSH} "curl -sf http://localhost:8000/api/v1/health | python3 -c \"import sys,json; print(json.load(sys.stdin).get('status',''))\" 2>/dev/null" || echo "")
  if [[ "${STATUS}" == "healthy" ]]; then
    echo "✅ Deployment successful — ${IMAGE}"
    exit 0
  fi
  echo "   waiting… (${i}/12)"
  sleep 5
done

echo "❌ Health check failed — consider running rollback.sh ${TARGET}"
exit 1

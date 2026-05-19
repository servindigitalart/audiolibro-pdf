#!/bin/bash
# Sonoro Celery Worker — Railway entrypoint
#
# Separate from start.sh (which runs Uvicorn + migrations) so that
# the worker Railway service can share Root Directory = services/api
# (required for "app.*" imports) without launching the API server.
#
# Railway worker service dashboard settings:
#   Root Directory : services/api
#   Start Command  : bash start-worker.sh
#
# The worker consumes three queues in priority order:
#   high_priority  — jobs with priority 1-3
#   normal         — jobs with priority 4-7  (upload default is priority=5)
#   low_priority   — jobs with priority 8-10

set -euo pipefail

export PYTHONPATH="${PYTHONPATH:+${PYTHONPATH}:}$(pwd)"

echo "[worker-startup] PYTHONPATH=${PYTHONPATH}"
echo "[worker-startup] Starting Celery worker..."

exec celery -A app.celery_app worker \
    --loglevel=info \
    --concurrency=2 \
    --queues=high_priority,normal,low_priority

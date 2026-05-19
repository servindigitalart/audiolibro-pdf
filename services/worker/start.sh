#!/bin/bash
# Sonoro Worker — Railway entrypoint
#
# Sets PYTHONPATH so that "app.*" imports resolve correctly.
# nixpacks does not add the working directory to sys.path automatically;
# without this, "celery -A app.celery_app worker" fails with:
#   ModuleNotFoundError: No module named 'app'
#
# Railway dashboard must set Root Directory = services/api for this service
# so that $(pwd) resolves to the directory containing the app/ package.

set -euo pipefail

export PYTHONPATH="${PYTHONPATH:+${PYTHONPATH}:}$(pwd)"

echo "[worker-startup] PYTHONPATH=${PYTHONPATH}"
echo "[worker-startup] Starting Celery worker..."

exec celery -A app.celery_app worker \
    --loglevel=info \
    --concurrency=2 \
    --queues=high_priority,normal,low_priority

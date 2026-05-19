#!/bin/bash
# Sonoro API — Railway entrypoint
#
# Runs Alembic migrations to head before starting Uvicorn.
# This ensures migration 012 (and all future migrations) are applied
# automatically on every deploy without manual intervention.
#
# Behaviour:
#   - Retries migrations up to 5 times with a 5-second back-off to handle
#     the window where Railway starts the API and the DB concurrently.
#   - Exits non-zero immediately if all retries are exhausted (Railway will
#     mark the deploy as failed and not route traffic to the broken instance).
#   - Replaces the shell with exec uvicorn so Railway's SIGTERM reaches the
#     server process directly (clean shutdown, no signal relay needed).

set -euo pipefail

MAX_RETRIES=5
RETRY_DELAY=5

echo "[startup] Running database migrations..."

for attempt in $(seq 1 $MAX_RETRIES); do
    if alembic upgrade head; then
        echo "[startup] Migrations applied successfully."
        break
    fi

    if [ "$attempt" -eq "$MAX_RETRIES" ]; then
        echo "[startup] ERROR: Migrations failed after $MAX_RETRIES attempts. Aborting." >&2
        exit 1
    fi

    echo "[startup] Migration attempt $attempt failed — retrying in ${RETRY_DELAY}s..." >&2
    sleep $RETRY_DELAY
done

echo "[startup] Starting Uvicorn..."
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"

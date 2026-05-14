#!/usr/bin/env bash
# migrate.sh — Alembic migration management
#
# Usage:
#   ./infra/scripts/migrate.sh up            # Apply all pending migrations
#   ./infra/scripts/migrate.sh down <rev>    # Downgrade to revision (e.g. -1 or abc123)
#   ./infra/scripts/migrate.sh status        # Show current revision
#   ./infra/scripts/migrate.sh history       # Show migration history
#   ./infra/scripts/migrate.sh generate <msg># Auto-generate a new migration
#
# Environment:
#   DATABASE_URL must be set (sync driver, e.g. postgresql://...)
#   Alternatively set --env-file before calling this script.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
API_DIR="${REPO_ROOT}/services/api"

cd "${API_DIR}"

CMD="${1:-up}"

case "${CMD}" in
  up)
    echo "▶  Running migrations: upgrade head"
    alembic upgrade head
    echo "✅ Migrations complete"
    ;;

  down)
    REVISION="${2:?Usage: migrate.sh down <revision|'-1'>}"
    echo "▶  Running migrations: downgrade to ${REVISION}"
    alembic downgrade "${REVISION}"
    echo "✅ Downgrade complete"
    ;;

  status)
    echo "▶  Current migration status:"
    alembic current
    ;;

  history)
    echo "▶  Migration history:"
    alembic history --verbose
    ;;

  generate)
    MESSAGE="${2:?Usage: migrate.sh generate '<description>'}"
    echo "▶  Generating migration: ${MESSAGE}"
    alembic revision --autogenerate -m "${MESSAGE}"
    echo "✅ Migration file created — review before committing"
    ;;

  *)
    echo "Unknown command: ${CMD}"
    echo "Valid commands: up | down <rev> | status | history | generate <msg>"
    exit 1
    ;;
esac

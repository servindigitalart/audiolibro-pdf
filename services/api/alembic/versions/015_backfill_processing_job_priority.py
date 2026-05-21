"""015_backfill_processing_job_priority

Revision ID: 015
Revises: 014
Create Date: 2026-05-21

WHY THIS MIGRATION EXISTS
--------------------------
The processing_jobs.priority column was defined as nullable=False with a
Python-side default=5, but no server_default.  When ProcessingJob rows were
created by passing priority=None explicitly (e.g. request.priority was None
because the upload client omitted the field), SQLAlchemy included NULL in the
INSERT, bypassing the Python-side default.  Because asyncpg sends the INSERT
with an explicit NULL value, PostgreSQL accepted it despite nullable=False
(the constraint is enforced at the statement level, and NULL was explicitly
supplied).

The fix has two parts:
1. Set a server_default of '5' so PostgreSQL fills in 5 even when the column
   is omitted or explicitly NULL at the wire level.
2. Backfill any existing rows where priority IS NULL to 5.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "015"
down_revision: Union[str, Sequence[str], None] = "014"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Backfill existing NULL rows before tightening the constraint.
    op.execute(
        "UPDATE processing_jobs SET priority = 5 WHERE priority IS NULL"
    )

    # Add a server-side default so future inserts that omit the column get 5.
    op.execute(
        "ALTER TABLE processing_jobs ALTER COLUMN priority SET DEFAULT 5"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE processing_jobs ALTER COLUMN priority DROP DEFAULT"
    )

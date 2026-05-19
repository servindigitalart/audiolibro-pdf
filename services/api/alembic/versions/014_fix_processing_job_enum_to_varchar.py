"""014_fix_processing_job_enum_to_varchar

Revision ID: 014
Revises: 013
Create Date: 2026-05-19

WHY THIS MIGRATION EXISTS
--------------------------
SQLAlchemy 2.0 + asyncpg has a bug where native PostgreSQL enum columns are
serialised through asyncpg's type codec using the Python enum member's .name
(uppercase: "CANCELLED") rather than its .value (lowercase: "cancelled").

Migration 006 created processing_jobs with two native PostgreSQL enum columns:
  jobtype   = ('full_process', 'preview', 'reprocess')
  jobstatus = ('queued', 'processing', 'completed', 'failed', 'cancelled')

The get_document_job polling endpoint queries:
  ProcessingJobModel.status != JobStatus.CANCELLED

asyncpg's native codec sends "CANCELLED" (member name) to the jobstatus enum,
which only knows "cancelled" (member value), raising:

  asyncpg.exceptions.InvalidTextRepresentationError:
    invalid input value for enum jobstatus: "CANCELLED"

Fix: convert both columns to VARCHAR(50), identical to what migration 012 did
for documents.upload_status and documents.processing_status.  The Python model
switches to Enum(..., native_enum=False) so SQLAlchemy sends .value strings
directly and bypasses asyncpg's native enum codec entirely.

Existing row data is unaffected — casting enum → text preserves the values.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "014"
down_revision: Union[str, Sequence[str], None] = "013"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """
    Convert job_type and status from native PostgreSQL ENUM to VARCHAR(50).
    Existing lowercase string data is preserved via the USING ... ::text cast.
    The now-unused enum types are then dropped.
    """
    # Drop indexes that reference the enum-typed columns before altering them.
    # Composite indexes first, simple ones are recreated below.
    op.drop_index("idx_processing_jobs_user_status", table_name="processing_jobs", if_exists=True)
    op.drop_index("idx_processing_jobs_status_created", table_name="processing_jobs", if_exists=True)
    op.drop_index("idx_processing_jobs_document_status", table_name="processing_jobs", if_exists=True)
    op.drop_index("ix_processing_jobs_job_type", table_name="processing_jobs", if_exists=True)
    op.drop_index("ix_processing_jobs_status", table_name="processing_jobs", if_exists=True)

    # Convert job_type: jobtype enum → VARCHAR(50)
    op.execute(
        "ALTER TABLE processing_jobs "
        "ALTER COLUMN job_type TYPE VARCHAR(50) "
        "USING job_type::text"
    )

    # Convert status: jobstatus enum → VARCHAR(50)
    op.execute(
        "ALTER TABLE processing_jobs "
        "ALTER COLUMN status TYPE VARCHAR(50) "
        "USING status::text"
    )

    # Set server-side defaults to match the Python enum values (lowercase)
    op.execute(
        "ALTER TABLE processing_jobs "
        "ALTER COLUMN job_type SET DEFAULT 'full_process'"
    )
    op.execute(
        "ALTER TABLE processing_jobs "
        "ALTER COLUMN status SET DEFAULT 'queued'"
    )

    # Drop the now-unused PostgreSQL enum types
    op.execute("DROP TYPE IF EXISTS jobtype")
    op.execute("DROP TYPE IF EXISTS jobstatus")

    # Recreate indexes on the new VARCHAR columns
    op.create_index("ix_processing_jobs_job_type", "processing_jobs", ["job_type"])
    op.create_index("ix_processing_jobs_status", "processing_jobs", ["status"])
    op.create_index(
        "idx_processing_jobs_user_status",
        "processing_jobs",
        ["user_id", "status"],
        postgresql_using="btree",
    )
    op.create_index(
        "idx_processing_jobs_status_created",
        "processing_jobs",
        ["status", "created_at"],
        postgresql_using="btree",
    )
    op.create_index(
        "idx_processing_jobs_document_status",
        "processing_jobs",
        ["document_id", "status"],
        postgresql_using="btree",
    )


def downgrade() -> None:
    """
    Revert VARCHAR columns back to native PostgreSQL ENUM types.
    Existing data must already contain only valid lowercase enum values.
    """
    op.drop_index("idx_processing_jobs_document_status", table_name="processing_jobs", if_exists=True)
    op.drop_index("idx_processing_jobs_status_created", table_name="processing_jobs", if_exists=True)
    op.drop_index("idx_processing_jobs_user_status", table_name="processing_jobs", if_exists=True)
    op.drop_index("ix_processing_jobs_status", table_name="processing_jobs", if_exists=True)
    op.drop_index("ix_processing_jobs_job_type", table_name="processing_jobs", if_exists=True)

    job_type_enum = postgresql.ENUM(
        "full_process", "preview", "reprocess",
        name="jobtype",
        create_type=True,
    )
    job_status_enum = postgresql.ENUM(
        "queued", "processing", "completed", "failed", "cancelled",
        name="jobstatus",
        create_type=True,
    )

    op.execute(
        "ALTER TABLE processing_jobs "
        "ALTER COLUMN job_type TYPE jobtype "
        "USING job_type::jobtype"
    )
    op.execute(
        "ALTER TABLE processing_jobs "
        "ALTER COLUMN status TYPE jobstatus "
        "USING status::jobstatus"
    )

    op.create_index("ix_processing_jobs_job_type", "processing_jobs", ["job_type"])
    op.create_index("ix_processing_jobs_status", "processing_jobs", ["status"])
    op.create_index(
        "idx_processing_jobs_user_status",
        "processing_jobs",
        ["user_id", "status"],
        postgresql_using="btree",
    )
    op.create_index(
        "idx_processing_jobs_status_created",
        "processing_jobs",
        ["status", "created_at"],
        postgresql_using="btree",
    )
    op.create_index(
        "idx_processing_jobs_document_status",
        "processing_jobs",
        ["document_id", "status"],
        postgresql_using="btree",
    )

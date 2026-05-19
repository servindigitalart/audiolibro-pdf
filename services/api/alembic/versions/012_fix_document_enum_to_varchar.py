"""012_fix_document_enum_to_varchar

Revision ID: 012
Revises: 011
Create Date: 2026-05-18

WHY THIS MIGRATION EXISTS
--------------------------
SQLAlchemy 2.0 + asyncpg has a bug where native PostgreSQL enum columns are
serialised through asyncpg's type codec using the Python enum member's .name
(uppercase: "PENDING") rather than its .value (lowercase: "pending").

The database was correctly created with lowercase enum values by migration 005:
  uploadstatus     = ('pending', 'uploaded', 'failed')
  processingstatus = ('not_started', 'queued', 'processing', 'assembling',
                      'finalizing', 'completed', 'failed')

But every INSERT raised:
  asyncpg.exceptions.InvalidTextRepresentationError:
    invalid input value for enum uploadstatus: "PENDING"

Fix: convert both columns to VARCHAR(50), which stores the same lowercase
string values without going through asyncpg's native enum codec.  The Python
model switches to Enum(..., native_enum=False) so SQLAlchemy treats the
column as plain text and sends .value strings directly.

Existing row data is unaffected — casting enum → text preserves the values.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "012"
down_revision: Union[str, Sequence[str], None] = "011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """
    Convert upload_status and processing_status from native PostgreSQL ENUM
    to VARCHAR(50).  Existing lowercase string data is preserved via the
    USING ... ::text cast.  The now-unused enum types are then dropped.
    """
    # Drop indexes that reference the enum-typed columns before altering them.
    # Composite indexes are dropped first; simple ones are recreated below.
    op.drop_index("idx_documents_upload_status", table_name="documents", if_exists=True)
    op.drop_index("idx_documents_processing_created", table_name="documents", if_exists=True)
    op.drop_index("ix_documents_upload_status", table_name="documents", if_exists=True)
    op.drop_index("ix_documents_processing_status", table_name="documents", if_exists=True)

    # Convert upload_status: uploadstatus enum → VARCHAR(50)
    op.execute(
        "ALTER TABLE documents "
        "ALTER COLUMN upload_status TYPE VARCHAR(50) "
        "USING upload_status::text"
    )

    # Convert processing_status: processingstatus enum → VARCHAR(50)
    op.execute(
        "ALTER TABLE documents "
        "ALTER COLUMN processing_status TYPE VARCHAR(50) "
        "USING processing_status::text"
    )

    # Set server-side defaults to match the Python enum values (lowercase)
    op.execute(
        "ALTER TABLE documents "
        "ALTER COLUMN upload_status SET DEFAULT 'pending'"
    )
    op.execute(
        "ALTER TABLE documents "
        "ALTER COLUMN processing_status SET DEFAULT 'not_started'"
    )

    # Drop the now-unused PostgreSQL enum types
    op.execute("DROP TYPE IF EXISTS uploadstatus")
    op.execute("DROP TYPE IF EXISTS processingstatus")

    # Recreate the indexes on the new VARCHAR columns
    op.create_index("ix_documents_upload_status", "documents", ["upload_status"])
    op.create_index("ix_documents_processing_status", "documents", ["processing_status"])
    op.create_index(
        "idx_documents_upload_status",
        "documents",
        ["upload_status", "created_at"],
        postgresql_using="btree",
    )
    op.create_index(
        "idx_documents_processing_created",
        "documents",
        ["processing_status", "created_at"],
        postgresql_using="btree",
    )


def downgrade() -> None:
    """
    Revert VARCHAR columns back to native PostgreSQL ENUM types.
    Existing data must already contain only valid lowercase enum values.
    """
    op.drop_index("idx_documents_processing_created", table_name="documents", if_exists=True)
    op.drop_index("idx_documents_upload_status", table_name="documents", if_exists=True)
    op.drop_index("ix_documents_processing_status", table_name="documents", if_exists=True)
    op.drop_index("ix_documents_upload_status", table_name="documents", if_exists=True)

    upload_status_enum = postgresql.ENUM(
        "pending", "uploaded", "failed",
        name="uploadstatus",
        create_type=True,
    )
    processing_status_enum = postgresql.ENUM(
        "not_started", "queued", "processing",
        "assembling", "finalizing", "completed", "failed",
        name="processingstatus",
        create_type=True,
    )

    op.execute(
        "ALTER TABLE documents "
        "ALTER COLUMN upload_status TYPE uploadstatus "
        "USING upload_status::uploadstatus"
    )
    op.execute(
        "ALTER TABLE documents "
        "ALTER COLUMN processing_status TYPE processingstatus "
        "USING processing_status::processingstatus"
    )

    op.create_index("ix_documents_upload_status", "documents", ["upload_status"])
    op.create_index("ix_documents_processing_status", "documents", ["processing_status"])
    op.create_index(
        "idx_documents_upload_status",
        "documents",
        ["upload_status", "created_at"],
        postgresql_using="btree",
    )
    op.create_index(
        "idx_documents_processing_created",
        "documents",
        ["processing_status", "created_at"],
        postgresql_using="btree",
    )

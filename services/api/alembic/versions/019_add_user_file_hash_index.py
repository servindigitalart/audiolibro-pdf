"""019_add_user_file_hash_index

Revision ID: 019
Revises: 018
Create Date: 2026-05-25

WHY THIS MIGRATION EXISTS
--------------------------
The documents table already has a single-column index on checksum_sha256
(created in migration 005).  Duplicate-PDF detection needs to look up
"does THIS user already have a document with THIS hash?" — a two-column
predicate.  Without a composite index the query does a sequential scan of
all documents matching the hash across every user, which is O(n) instead
of O(1).

This migration adds the composite index idx_documents_user_checksum on
(user_id, checksum_sha256) so the duplicate lookup is a covering index
scan limited to one user's documents.

No column changes — checksum_sha256 already exists and is NOT NULL.
"""

from alembic import op

revision = '019'
down_revision = '018'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "idx_documents_user_checksum",
        "documents",
        ["user_id", "checksum_sha256"],
    )


def downgrade() -> None:
    op.drop_index("idx_documents_user_checksum", table_name="documents")

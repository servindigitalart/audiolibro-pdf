"""026_add_chapter_unique_constraint

Revision ID: 026
Revises: 025
Create Date: 2026-05-31

Adds a unique constraint on (document_id, order_index) in the chapters table.

Without this constraint a Celery task retry could call _persist_chapters twice
for the same document, producing duplicate rows.  The duplicate rows caused
scalar_one_or_none() to raise MultipleResultsFound when the worker later
updated the chapter's audio_url.

_persist_chapters now deletes existing chapters before inserting (idempotent),
but this constraint is the DB-level safety net: if two workers ever race on the
same job the second INSERT will fail cleanly rather than silently producing an
inconsistent state.

The existing non-unique ix_chapters_document_order index already covers this
column pair for read performance, so no new index is needed.
"""

import sqlalchemy as sa
from alembic import op

revision = '026'
down_revision = '025'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Remove duplicate rows that may already exist before adding the constraint.
    # Keep the row with the smallest id (earliest insert) for each
    # (document_id, order_index) pair.
    op.execute("""
        DELETE FROM chapters
        WHERE id NOT IN (
            SELECT MIN(id::text)::uuid
            FROM chapters
            GROUP BY document_id, order_index
        )
    """)

    op.create_unique_constraint(
        "uq_chapters_document_order",
        "chapters",
        ["document_id", "order_index"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_chapters_document_order", "chapters", type_="unique")

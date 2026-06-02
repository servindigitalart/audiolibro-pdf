"""027_add_display_title_to_documents

Revision ID: 027
Revises: 026
Create Date: 2026-06-01

Adds display_title VARCHAR(512) to the documents table.
NULL means "use original_filename" — the UI falls back gracefully.
Users can rename their audiobook without touching the underlying file.
"""

import sqlalchemy as sa
from alembic import op

revision = '027'
down_revision = '026'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'documents',
        sa.Column('display_title', sa.String(512), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('documents', 'display_title')

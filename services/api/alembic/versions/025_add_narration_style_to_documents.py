"""025_add_narration_style_to_documents

Revision ID: 025
Revises: 024
Create Date: 2026-05-30

Adds narration_style VARCHAR(50) to the documents table so a completed
audiobook remembers the delivery profile used during generation.  This
enables future "regenerate with same style" flows and powers admin
completion-rate-by-profile analytics.

NULL means the document was generated before Phase 5H or the job is still
in progress — callers should treat NULL as "storytelling" (the default).
"""

import sqlalchemy as sa
from alembic import op

revision = '025'
down_revision = '024'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'documents',
        sa.Column('narration_style', sa.String(50), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('documents', 'narration_style')

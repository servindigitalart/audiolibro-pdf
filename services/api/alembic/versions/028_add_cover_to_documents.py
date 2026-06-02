"""028_add_cover_to_documents

Revision ID: 028
Revises: 027
Create Date: 2026-06-02

Adds cover_object_key VARCHAR(1024) to documents table.
NULL = use auto-generated cover art; non-NULL = path in object storage.
"""

import sqlalchemy as sa
from alembic import op

revision = '028'
down_revision = '027'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'documents',
        sa.Column('cover_object_key', sa.String(1024), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('documents', 'cover_object_key')

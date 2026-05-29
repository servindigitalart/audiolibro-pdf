"""024_add_narration_style_to_jobs

Revision ID: 024
Revises: 023
Create Date: 2026-05-29

Adds two nullable columns to processing_jobs so the user's narration-style
choice and explicit voice selection reach the Celery worker:

  narration_style    VARCHAR(50)  — calm | storytelling | documentary |
                                    podcast | educational | NULL (default)
  voice_id_override  VARCHAR(255) — Google voice name chosen in the preflight
                                    UI; NULL means use auto-detected voice
"""

import sqlalchemy as sa
from alembic import op

revision = '024'
down_revision = '023'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'processing_jobs',
        sa.Column('narration_style', sa.String(50), nullable=True),
    )
    op.add_column(
        'processing_jobs',
        sa.Column('voice_id_override', sa.String(255), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('processing_jobs', 'voice_id_override')
    op.drop_column('processing_jobs', 'narration_style')

"""018_add_language_detection_confidence

Revision ID: 018
Revises: 017
Create Date: 2026-05-25

WHY THIS MIGRATION EXISTS
--------------------------
Adds language_detection_confidence to documents so the pipeline can persist
the langdetect probability score alongside the detected language code.
The confidence is used for diagnostics and future quality-gate logic.

The language_detected column (VARCHAR 10) already exists from migration 005.
"""

from alembic import op
import sqlalchemy as sa

revision = '018'
down_revision = '017'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'documents',
        sa.Column(
            'language_detection_confidence',
            sa.Float(),
            nullable=True,
            comment='langdetect confidence score 0.0–1.0; NULL when detection failed/skipped',
        ),
    )


def downgrade() -> None:
    op.drop_column('documents', 'language_detection_confidence')

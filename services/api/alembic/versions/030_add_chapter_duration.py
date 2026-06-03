"""030_add_chapter_duration

Revision ID: 030
Revises: 029
Create Date: 2026-06-03

Adds duration_seconds and start_time_seconds to the chapters table.

duration_seconds: length of this chapter's audio segment.
start_time_seconds: byte offset within the full concatenated audiobook,
  enabling seek-to-chapter without splitting the audio file.

Both nullable — existing rows are unaffected.
"""

import sqlalchemy as sa
from alembic import op

revision = '030'
down_revision = '029'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'chapters',
        sa.Column('duration_seconds', sa.Float(), nullable=True,
                  comment='Duration of this chapter audio in seconds')
    )
    op.add_column(
        'chapters',
        sa.Column('start_time_seconds', sa.Float(), nullable=True,
                  comment='Start offset within the full audiobook in seconds')
    )


def downgrade():
    op.drop_column('chapters', 'start_time_seconds')
    op.drop_column('chapters', 'duration_seconds')

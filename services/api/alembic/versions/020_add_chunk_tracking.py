"""020_add_chunk_tracking

Revision ID: 020
Revises: 019
Create Date: 2026-05-25

WHY THIS MIGRATION EXISTS
--------------------------
The frontend polls /{document_id}/job to show processing progress.  Previously
the worker only wrote a coarse per-chapter percentage (e.g. 30%, 60%, 90%),
so a large document with many TTS chunks could sit at 30% for many minutes
with no visible movement — users couldn't tell whether processing was alive.

This migration adds three columns to processing_jobs that let the worker
report progress at TTS-chunk granularity (each chunk is ~4 500 characters,
roughly 30–60 seconds of audio):

  total_chunks      — total TTS chunks across all chapters, set once before
                      the TTS loop starts (allows a %-complete denominator)
  completed_chunks  — incremented after each chunk is synthesised; the
                      polling endpoint converts this to a smooth 25–90%
                      progress value
  current_stage     — human-readable stage name stored in DB so the frontend
                      can display accurate labels without percentage heuristics
                      ('analyzing', 'chapter_detection', 'tts_generation',
                       'final_assembly', 'upload_finalize')

Both integer columns default to 0 so existing in-flight rows are valid.
current_stage is nullable — NULL means the job predates this migration.
"""

import sqlalchemy as sa
from alembic import op

revision = '020'
down_revision = '019'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "processing_jobs",
        sa.Column("total_chunks", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "processing_jobs",
        sa.Column("completed_chunks", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "processing_jobs",
        sa.Column("current_stage", sa.String(50), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("processing_jobs", "current_stage")
    op.drop_column("processing_jobs", "completed_chunks")
    op.drop_column("processing_jobs", "total_chunks")

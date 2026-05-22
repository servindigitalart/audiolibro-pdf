"""017_add_chapter_audio_url

Revision ID: 017
Revises: 016
Create Date: 2026-05-22

WHY THIS MIGRATION EXISTS
--------------------------
The Chapter model needs to persist the S3 key of its assembled audio file so
that the /documents/{id}/chapters endpoint can generate presigned playback URLs.

Previously, processing.py uploaded each chapter's audio to S3 but never stored
the path in the DB, so the AudioPlayer had no way to stream per-chapter audio
and always showed "Generating your audiobook…" even after processing completed.
"""

from alembic import op
import sqlalchemy as sa

revision = '017'
down_revision = '016'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'chapters',
        sa.Column('audio_url', sa.String(length=1024), nullable=True),
    )

    # Backfill: for documents that have already been processed (final_audio_path IS NOT NULL),
    # reconstruct the per-chapter S3 key from the deterministic path convention used by the
    # processing pipeline: audio/<user_id>/<document_id>/chapter_<order_index+1>.mp3
    # This matches _storage_path_for_audio() + the filename=f"chapter_{i+1}.mp3" in processing.py.
    op.execute(
        """
        UPDATE chapters c
        SET audio_url = 'audio/' || d.user_id::text
                        || '/' || c.document_id::text
                        || '/chapter_' || (c.order_index + 1)::text || '.mp3'
        FROM documents d
        WHERE c.document_id = d.id
          AND c.audio_url IS NULL
          AND d.final_audio_path IS NOT NULL
        """
    )


def downgrade() -> None:
    op.drop_column('chapters', 'audio_url')

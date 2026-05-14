"""
Add audio assembly fields to documents

Revision ID: 008
Revises: 007
Create Date: 2026-02-11

BLOCK 6C: Audio Assembly & Output Layer
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers
revision = '008'
down_revision = '007_chapters'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add audio assembly fields and new processing statuses."""
    
    # Add new columns to documents table
    op.add_column(
        'documents',
        sa.Column('final_audio_path', sa.String(length=1024), nullable=True, comment='Path to final assembled audiobook MP3')
    )
    
    op.add_column(
        'documents',
        sa.Column('audio_duration_seconds', sa.Integer(), nullable=True, comment='Total audiobook duration in seconds')
    )
    
    op.add_column(
        'documents',
        sa.Column('audio_file_size_bytes', sa.BigInteger(), nullable=True, comment='Final audiobook file size in bytes')
    )
    
    # Update ProcessingStatus enum to include new statuses
    # Note: This requires a more complex migration for PostgreSQL enums
    # We'll use ALTER TYPE with a temporary type
    
    # Create new enum type with additional values
    op.execute("ALTER TYPE processingstatus ADD VALUE IF NOT EXISTS 'assembling'")
    op.execute("ALTER TYPE processingstatus ADD VALUE IF NOT EXISTS 'finalizing'")


def downgrade() -> None:
    """Remove audio assembly fields and new processing statuses."""
    
    # Remove columns
    op.drop_column('documents', 'audio_file_size_bytes')
    op.drop_column('documents', 'audio_duration_seconds')
    op.drop_column('documents', 'final_audio_path')
    
    # Note: Removing enum values is more complex and requires creating a new type
    # For simplicity, we'll leave the enum values in place
    # In production, you might want to recreate the enum type entirely

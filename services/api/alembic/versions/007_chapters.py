"""
Add chapters table for chapter detection

Revision ID: 007
Revises: 006
Create Date: 2026-02-11

BLOCK 6B: Text Segmentation & Chapter Detection Layer
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers
revision = '007_chapters'
down_revision = '006_processing_jobs'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create chapters table and indexes."""
    
    # Create chapters table
    op.create_table(
        'chapters',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column('document_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('title', sa.String(length=512), nullable=False),
        sa.Column('start_page', sa.Integer(), nullable=False),
        sa.Column('end_page', sa.Integer(), nullable=False),
        sa.Column('order_index', sa.Integer(), nullable=False),
        sa.Column('confidence_score', sa.Float(), nullable=False, server_default='0.0'),
        sa.Column('detection_method', sa.String(length=50), nullable=True),
        sa.Column('char_count', sa.BigInteger(), nullable=False, server_default='0'),
        sa.Column('text_preview', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('now()')),
        sa.ForeignKeyConstraint(['document_id'], ['documents.id'], ondelete='CASCADE'),
    )
    
    # Create indexes
    # Primary key index is created automatically
    op.create_index('ix_chapters_id', 'chapters', ['id'])
    
    # Query chapters by document
    op.create_index('ix_chapters_document_id', 'chapters', ['document_id'])
    
    # Query chapters by document in order
    op.create_index(
        'ix_chapters_document_order',
        'chapters',
        ['document_id', 'order_index']
    )
    
    # Query chapters by document and page range
    op.create_index(
        'ix_chapters_document_pages',
        'chapters',
        ['document_id', 'start_page', 'end_page']
    )
    
    # Query chapters by confidence score
    op.create_index('ix_chapters_confidence', 'chapters', ['confidence_score'])
    
    # Query chapters by detection method
    op.create_index('ix_chapters_detection_method', 'chapters', ['detection_method'])


def downgrade() -> None:
    """Drop chapters table and indexes."""
    
    # Drop indexes first
    op.drop_index('ix_chapters_detection_method', table_name='chapters')
    op.drop_index('ix_chapters_confidence', table_name='chapters')
    op.drop_index('ix_chapters_document_pages', table_name='chapters')
    op.drop_index('ix_chapters_document_order', table_name='chapters')
    op.drop_index('ix_chapters_document_id', table_name='chapters')
    op.drop_index('ix_chapters_id', table_name='chapters')
    
    # Drop table
    op.drop_table('chapters')

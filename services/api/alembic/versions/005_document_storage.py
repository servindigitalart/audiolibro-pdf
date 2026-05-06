"""005_document_storage

Revision ID: 005_document_storage
Revises: 004_account_domain
Create Date: 2026-02-11 14:00:00.000000

BLOCK 5A: Document Upload & Storage Layer
==========================================
Creates the documents table for PDF ingestion and lifecycle tracking.

This migration adds:
- documents table with full metadata tracking
- Upload and processing status enums
- Storage path and checksum fields
- Lightweight metadata fields (page_count, character_estimate, language)
- Performance indexes for common queries

Security: All documents are private, access via pre-signed URLs only.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '005_document_storage'
down_revision: Union[str, None] = '004_account_domain'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create documents table and related infrastructure."""
    
    # Create upload status enum
    upload_status_enum = postgresql.ENUM(
        'pending',
        'uploaded',
        'failed',
        name='uploadstatus',
        create_type=True
    )
    upload_status_enum.create(op.get_bind())
    
    # Create processing status enum
    processing_status_enum = postgresql.ENUM(
        'not_started',
        'queued',
        'processing',
        'completed',
        'failed',
        name='processingstatus',
        create_type=True
    )
    processing_status_enum.create(op.get_bind())
    
    # Create documents table
    op.create_table(
        'documents',
        
        # Identity
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False, comment='Unique document identifier'),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), nullable=False, comment='Document owner'),
        
        # File metadata
        sa.Column('filename', sa.String(length=255), nullable=False, comment='Sanitized filename used in storage'),
        sa.Column('original_filename', sa.String(length=512), nullable=False, comment='Original filename from upload'),
        sa.Column('file_size_bytes', sa.BigInteger(), nullable=False, comment='File size in bytes'),
        sa.Column('mime_type', sa.String(length=100), nullable=False, server_default='application/pdf', comment='MIME type (validated)'),
        
        # Storage
        sa.Column('storage_path', sa.String(length=1024), nullable=False, comment='Full S3 object key'),
        sa.Column('checksum_sha256', sa.String(length=64), nullable=False, comment='SHA256 hash for integrity verification'),
        
        # Status tracking
        sa.Column('upload_status', upload_status_enum, nullable=False, server_default='pending', comment='Upload completion status'),
        sa.Column('processing_status', processing_status_enum, nullable=False, server_default='not_started', comment='Processing pipeline status'),
        
        # Document analysis (lightweight metadata)
        sa.Column('page_count', sa.Integer(), nullable=True, comment='Number of pages in PDF'),
        sa.Column('character_estimate', sa.BigInteger(), nullable=True, comment='Rough character count estimate'),
        sa.Column('language_detected', sa.String(length=10), nullable=True, comment="ISO 639-1 language code (e.g., 'en', 'es')"),
        
        # Error tracking
        sa.Column('error_message', sa.Text(), nullable=True, comment='Error details if upload or processing failed'),
        
        # Timestamps
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('now()'), comment='Upload initiated timestamp'),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.text('now()'), comment='Last modification timestamp'),
        sa.Column('uploaded_at', sa.DateTime(), nullable=True, comment='Storage completion timestamp'),
        sa.Column('processing_started_at', sa.DateTime(), nullable=True, comment='Processing initiation timestamp'),
        sa.Column('processing_completed_at', sa.DateTime(), nullable=True, comment='Processing completion timestamp'),
        
        # Constraints
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.UniqueConstraint('storage_path', name='uq_documents_storage_path'),
    )
    
    # Create indexes for performance
    op.create_index('ix_documents_id', 'documents', ['id'])
    op.create_index('ix_documents_user_id', 'documents', ['user_id'])
    op.create_index('ix_documents_checksum_sha256', 'documents', ['checksum_sha256'])
    op.create_index('ix_documents_upload_status', 'documents', ['upload_status'])
    op.create_index('ix_documents_processing_status', 'documents', ['processing_status'])
    
    # Composite indexes for common queries
    op.create_index('idx_documents_user_created', 'documents', ['user_id', 'created_at'], postgresql_using='btree')
    op.create_index('idx_documents_processing_created', 'documents', ['processing_status', 'created_at'], postgresql_using='btree')
    op.create_index('idx_documents_upload_status', 'documents', ['upload_status', 'created_at'], postgresql_using='btree')


def downgrade() -> None:
    """Drop documents table and related infrastructure."""
    
    # Drop indexes
    op.drop_index('idx_documents_upload_status', table_name='documents')
    op.drop_index('idx_documents_processing_created', table_name='documents')
    op.drop_index('idx_documents_user_created', table_name='documents')
    op.drop_index('ix_documents_processing_status', table_name='documents')
    op.drop_index('ix_documents_upload_status', table_name='documents')
    op.drop_index('ix_documents_checksum_sha256', table_name='documents')
    op.drop_index('ix_documents_user_id', table_name='documents')
    op.drop_index('ix_documents_id', table_name='documents')
    
    # Drop table
    op.drop_table('documents')
    
    # Drop enums
    processing_status_enum = postgresql.ENUM(name='processingstatus')
    processing_status_enum.drop(op.get_bind())
    
    upload_status_enum = postgresql.ENUM(name='uploadstatus')
    upload_status_enum.drop(op.get_bind())

"""006_processing_jobs

Revision ID: 006_processing_jobs
Revises: 005_document_storage
Create Date: 2026-02-11 16:00:00.000000

BLOCK 5B: Processing Orchestration Layer
=========================================
Creates the processing_jobs table for Celery task orchestration.

This migration adds:
- processing_jobs table with job tracking
- Job type and status enums
- Progress and error tracking fields
- Celery task ID linking
- Performance indexes for queue management

Pure infrastructure - no TTS business logic.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '006_processing_jobs'
down_revision: Union[str, None] = '005_document_storage'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create processing_jobs table and related infrastructure."""
    
    # Create job type enum
    job_type_enum = postgresql.ENUM(
        'full_process',
        'preview',
        'reprocess',
        name='jobtype',
        create_type=True
    )
    job_type_enum.create(op.get_bind())
    
    # Create job status enum
    job_status_enum = postgresql.ENUM(
        'queued',
        'processing',
        'completed',
        'failed',
        'cancelled',
        name='jobstatus',
        create_type=True
    )
    job_status_enum.create(op.get_bind())
    
    # Create processing_jobs table
    op.create_table(
        'processing_jobs',
        
        # Identity
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False, comment='Unique job identifier'),
        
        # References
        sa.Column('document_id', postgresql.UUID(as_uuid=True), nullable=False, comment='Document being processed'),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), nullable=False, comment='Job owner'),
        
        # Job configuration
        sa.Column('job_type', job_type_enum, nullable=False, server_default='full_process', comment='Type of processing job'),
        sa.Column('priority', sa.Integer(), nullable=False, server_default='5', comment='Job priority (1=highest, 10=lowest)'),
        
        # Status tracking
        sa.Column('status', job_status_enum, nullable=False, server_default='queued', comment='Current job status'),
        sa.Column('progress_percentage', sa.Integer(), nullable=False, server_default='0', comment='Processing progress (0-100)'),
        
        # Error handling
        sa.Column('error_message', sa.Text(), nullable=True, comment='Error details if job failed'),
        sa.Column('retry_count', sa.Integer(), nullable=False, server_default='0', comment='Number of retry attempts'),
        
        # Celery task tracking
        sa.Column('celery_task_id', sa.String(length=255), nullable=True, comment='Celery task ID for tracking'),
        
        # Timestamps
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('now()'), comment='Job creation timestamp'),
        sa.Column('started_at', sa.DateTime(), nullable=True, comment='Processing start timestamp'),
        sa.Column('completed_at', sa.DateTime(), nullable=True, comment='Processing completion timestamp'),
        sa.Column('cancelled_at', sa.DateTime(), nullable=True, comment='Cancellation timestamp'),
        
        # Constraints
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['document_id'], ['documents.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.CheckConstraint('progress_percentage >= 0 AND progress_percentage <= 100', name='ck_progress_percentage_range'),
        sa.CheckConstraint('priority >= 1 AND priority <= 10', name='ck_priority_range'),
    )
    
    # Create indexes for performance
    op.create_index('ix_processing_jobs_id', 'processing_jobs', ['id'])
    op.create_index('ix_processing_jobs_document_id', 'processing_jobs', ['document_id'])
    op.create_index('ix_processing_jobs_user_id', 'processing_jobs', ['user_id'])
    op.create_index('ix_processing_jobs_job_type', 'processing_jobs', ['job_type'])
    op.create_index('ix_processing_jobs_status', 'processing_jobs', ['status'])
    op.create_index('ix_processing_jobs_created_at', 'processing_jobs', ['created_at'])
    op.create_index('ix_processing_jobs_celery_task_id', 'processing_jobs', ['celery_task_id'])
    
    # Composite indexes for common queries
    op.create_index('idx_processing_jobs_user_created', 'processing_jobs', ['user_id', 'created_at'], postgresql_using='btree')
    op.create_index('idx_processing_jobs_user_status', 'processing_jobs', ['user_id', 'status'], postgresql_using='btree')
    op.create_index('idx_processing_jobs_status_created', 'processing_jobs', ['status', 'created_at'], postgresql_using='btree')
    op.create_index('idx_processing_jobs_document_status', 'processing_jobs', ['document_id', 'status'], postgresql_using='btree')


def downgrade() -> None:
    """Drop processing_jobs table and related infrastructure."""
    
    # Drop composite indexes
    op.drop_index('idx_processing_jobs_document_status', table_name='processing_jobs')
    op.drop_index('idx_processing_jobs_status_created', table_name='processing_jobs')
    op.drop_index('idx_processing_jobs_user_status', table_name='processing_jobs')
    op.drop_index('idx_processing_jobs_user_created', table_name='processing_jobs')
    
    # Drop simple indexes
    op.drop_index('ix_processing_jobs_celery_task_id', table_name='processing_jobs')
    op.drop_index('ix_processing_jobs_created_at', table_name='processing_jobs')
    op.drop_index('ix_processing_jobs_status', table_name='processing_jobs')
    op.drop_index('ix_processing_jobs_job_type', table_name='processing_jobs')
    op.drop_index('ix_processing_jobs_user_id', table_name='processing_jobs')
    op.drop_index('ix_processing_jobs_document_id', table_name='processing_jobs')
    op.drop_index('ix_processing_jobs_id', table_name='processing_jobs')
    
    # Drop table
    op.drop_table('processing_jobs')
    
    # Drop enums
    job_status_enum = postgresql.ENUM(name='jobstatus')
    job_status_enum.drop(op.get_bind())
    
    job_type_enum = postgresql.ENUM(name='jobtype')
    job_type_enum.drop(op.get_bind())

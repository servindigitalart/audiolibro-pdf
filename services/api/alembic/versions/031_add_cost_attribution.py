"""031_add_cost_attribution

Revision ID: 031
Revises: 030
Create Date: 2026-08-10

Phase 0C — makes provider spend attributable and failed work observable.

cost_events gains:
  document_id, job_id  — real indexed FKs.  These were previously buried in the
    metadata JSON, so "what did this audiobook cost" and "what did failed jobs
    cost" were not answerable with an indexed query.
  voice_id             — per-voice cost attribution.
  success              — a failed provider attempt is recorded with
    success=false and total_cost=0 (Google does not bill failed requests), so
    failed work stays countable without inventing a charge.
  failure_reason       — exception class name for failed attempts.
  attempt_number       — 1 = first try, >1 = retry, so retries are countable
    without being double-charged.

processing_jobs gains:
  calculated_cost_usd  — post-synthesis cost from characters actually sent.
    estimated_cost_usd keeps its column but changes meaning: it is now written
    BEFORE generation.  Existing rows hold a post-completion value; both are a
    cost for the same job, so no row is wrong, only less precise.

All columns are nullable or defaulted.  No backfill, no data loss, and the FKs
use ON DELETE SET NULL so deleting a document never deletes its cost history.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = '031'
down_revision = '030'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'cost_events',
        sa.Column('document_id', UUID(as_uuid=True), nullable=True,
                  comment='Document this cost belongs to, when applicable')
    )
    op.add_column(
        'cost_events',
        sa.Column('job_id', UUID(as_uuid=True), nullable=True,
                  comment='Processing job this cost belongs to, when applicable')
    )
    op.add_column(
        'cost_events',
        sa.Column('voice_id', sa.String(length=255), nullable=True,
                  comment='TTS voice used, for per-voice cost attribution')
    )
    op.add_column(
        'cost_events',
        sa.Column('success', sa.Boolean(), nullable=False, server_default='true',
                  comment='True when the provider call succeeded, False when it failed')
    )
    op.add_column(
        'cost_events',
        sa.Column('failure_reason', sa.String(length=255), nullable=True,
                  comment="Exception class name when success is 'false'")
    )
    op.add_column(
        'cost_events',
        sa.Column('attempt_number', sa.Integer(), nullable=False, server_default='1',
                  comment='Provider attempt for this logical chunk (1 = first try, >1 = retry)')
    )

    # total_cost keeps its type and values but changes meaning: it is a cost we
    # calculate from published per-character rates, never an invoiced amount.
    # The old comment read "Total cost in USD", which is exactly the reading
    # Phase 0C exists to prevent.
    op.alter_column(
        'cost_events', 'total_cost',
        existing_type=sa.Float(), existing_nullable=False,
        comment='Calculated provider cost in USD (quantity * unit_cost) — not an invoice amount',
    )

    op.create_foreign_key(
        'fk_cost_events_document_id', 'cost_events', 'documents',
        ['document_id'], ['id'], ondelete='SET NULL',
    )
    op.create_foreign_key(
        'fk_cost_events_job_id', 'cost_events', 'processing_jobs',
        ['job_id'], ['id'], ondelete='SET NULL',
    )
    op.create_index('ix_cost_events_document_id', 'cost_events', ['document_id'])
    op.create_index('ix_cost_events_job_id', 'cost_events', ['job_id'])
    # Drives the failed-spend and retry reports on the admin dashboard.
    op.create_index('idx_cost_events_success_created', 'cost_events', ['success', 'created_at'])

    op.add_column(
        'processing_jobs',
        sa.Column('calculated_cost_usd', sa.Float(), nullable=True,
                  comment='Calculated provider cost from characters actually synthesized')
    )


def downgrade():
    op.drop_column('processing_jobs', 'calculated_cost_usd')

    op.alter_column(
        'cost_events', 'total_cost',
        existing_type=sa.Float(), existing_nullable=False,
        comment='Total cost in USD (quantity * unit_cost)',
    )

    op.drop_index('idx_cost_events_success_created', table_name='cost_events')
    op.drop_index('ix_cost_events_job_id', table_name='cost_events')
    op.drop_index('ix_cost_events_document_id', table_name='cost_events')
    op.drop_constraint('fk_cost_events_job_id', 'cost_events', type_='foreignkey')
    op.drop_constraint('fk_cost_events_document_id', 'cost_events', type_='foreignkey')

    op.drop_column('cost_events', 'attempt_number')
    op.drop_column('cost_events', 'failure_reason')
    op.drop_column('cost_events', 'success')
    op.drop_column('cost_events', 'voice_id')
    op.drop_column('cost_events', 'job_id')
    op.drop_column('cost_events', 'document_id')

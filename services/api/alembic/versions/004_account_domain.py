"""Add account domain tables

Revision ID: 004_account_domain
Revises: 003_cost_governance
Create Date: 2026-02-11

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '004_account_domain'
down_revision = '003_cost_governance'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create account_preferences table
    op.create_table(
        'account_preferences',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('preferred_language', sa.String(length=10), nullable=False, server_default='en'),
        sa.Column('preferred_voice', sa.String(length=100), nullable=True),
        sa.Column('timezone', sa.String(length=50), nullable=False, server_default='UTC'),
        sa.Column('currency', sa.String(length=3), nullable=False, server_default='USD'),
        sa.Column('email_notifications', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('marketing_emails', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('usage_alerts', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_account_preferences_user_id'), 'account_preferences', ['user_id'], unique=True)
    
    # Create user_activity_log table
    op.create_table(
        'user_activity_log',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('activity_type', sa.String(length=50), nullable=False),
        sa.Column('description', sa.Text(), nullable=False),
        sa.Column('ip_address', sa.String(length=45), nullable=True),
        sa.Column('user_agent', sa.Text(), nullable=True),
        sa.Column('metadata', postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column('is_suspicious', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_user_activity_log_user_id'), 'user_activity_log', ['user_id'], unique=False)
    op.create_index(op.f('ix_user_activity_log_activity_type'), 'user_activity_log', ['activity_type'], unique=False)
    op.create_index(op.f('ix_user_activity_log_created_at'), 'user_activity_log', ['created_at'], unique=False)
    op.create_index('idx_user_activity_created', 'user_activity_log', ['user_id', 'created_at'], unique=False)
    op.create_index('idx_activity_type_created', 'user_activity_log', ['activity_type', 'created_at'], unique=False)
    op.create_index('idx_suspicious_activities', 'user_activity_log', ['is_suspicious', 'created_at'], unique=False)


def downgrade() -> None:
    # Drop user_activity_log table
    op.drop_index('idx_suspicious_activities', table_name='user_activity_log')
    op.drop_index('idx_activity_type_created', table_name='user_activity_log')
    op.drop_index('idx_user_activity_created', table_name='user_activity_log')
    op.drop_index(op.f('ix_user_activity_log_created_at'), table_name='user_activity_log')
    op.drop_index(op.f('ix_user_activity_log_activity_type'), table_name='user_activity_log')
    op.drop_index(op.f('ix_user_activity_log_user_id'), table_name='user_activity_log')
    op.drop_table('user_activity_log')
    
    # Drop account_preferences table
    op.drop_index(op.f('ix_account_preferences_user_id'), table_name='account_preferences')
    op.drop_table('account_preferences')

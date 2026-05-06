"""Add cost governance tables

Revision ID: 003_cost_governance
Revises: 002_add_auth_fields
Create Date: 2026-02-11

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '003_cost_governance'
down_revision = '002_add_auth_fields'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add plan_tier column to users table
    op.add_column(
        'users',
        sa.Column('plan_tier', sa.String(length=20), nullable=False, server_default='FREE')
    )
    op.create_index(op.f('ix_users_plan_tier'), 'users', ['plan_tier'], unique=False)
    
    # Create cost_events table
    op.create_table(
        'cost_events',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            'event_type',
            sa.Enum(
                'TTS_GENERATION',
                'TTS_STREAMING',
                'STORAGE_UPLOAD',
                'STORAGE_HOSTING',
                'STORAGE_TRANSFER',
                'API_CALL_EXTERNAL',
                'API_CALL_INTERNAL',
                'COMPUTE_PROCESSING',
                'EMAIL_SENT',
                'CDN_BANDWIDTH',
                'DATABASE_QUERY',
                'CREDIT_PURCHASE',
                'CREDIT_USAGE',
                'INFRASTRUCTURE_HOSTING',
                'INFRASTRUCTURE_DATABASE',
                name='costeventtype',
            ),
            nullable=False,
        ),
        sa.Column(
            'provider',
            sa.Enum(
                'OPENAI',
                'ANTHROPIC',
                'ELEVEN_LABS',
                'DIGITALOCEAN',
                'AWS_S3',
                'SENDGRID',
                'INTERNAL',
                name='costprovider',
            ),
            nullable=True,
        ),
        sa.Column('quantity', sa.Float(), nullable=False, server_default='1.0'),
        sa.Column('unit_cost', sa.Float(), nullable=False, server_default='0.0'),
        sa.Column('total_cost', sa.Float(), nullable=False, server_default='0.0'),
        sa.Column('metadata', postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('now()')),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_cost_events_id'), 'cost_events', ['id'], unique=False)
    op.create_index(op.f('ix_cost_events_user_id'), 'cost_events', ['user_id'], unique=False)
    op.create_index(op.f('ix_cost_events_event_type'), 'cost_events', ['event_type'], unique=False)
    op.create_index(op.f('ix_cost_events_created_at'), 'cost_events', ['created_at'], unique=False)
    op.create_index('idx_user_created', 'cost_events', ['user_id', 'created_at'], unique=False)
    op.create_index('idx_event_type_created', 'cost_events', ['event_type', 'created_at'], unique=False)
    op.create_index('idx_provider_created', 'cost_events', ['provider', 'created_at'], unique=False)
    
    # Create usage_quotas table
    op.create_table(
        'usage_quotas',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('period_start', sa.DateTime(), nullable=False, server_default=sa.text('now()')),
        sa.Column('period_end', sa.DateTime(), nullable=False),
        sa.Column('characters_used', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('jobs_created', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('storage_used_mb', sa.Float(), nullable=False, server_default='0.0'),
        sa.Column('api_calls', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.text('now()')),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_usage_quotas_user_id'), 'usage_quotas', ['user_id'], unique=True)


def downgrade() -> None:
    # Drop usage_quotas table
    op.drop_index(op.f('ix_usage_quotas_user_id'), table_name='usage_quotas')
    op.drop_table('usage_quotas')
    
    # Drop cost_events table
    op.drop_index('idx_provider_created', table_name='cost_events')
    op.drop_index('idx_event_type_created', table_name='cost_events')
    op.drop_index('idx_user_created', table_name='cost_events')
    op.drop_index(op.f('ix_cost_events_created_at'), table_name='cost_events')
    op.drop_index(op.f('ix_cost_events_event_type'), table_name='cost_events')
    op.drop_index(op.f('ix_cost_events_user_id'), table_name='cost_events')
    op.drop_index(op.f('ix_cost_events_id'), table_name='cost_events')
    op.drop_table('cost_events')
    
    # Drop enums
    sa.Enum(name='costprovider').drop(op.get_bind(), checkfirst=False)
    sa.Enum(name='costeventtype').drop(op.get_bind(), checkfirst=False)
    
    # Remove plan_tier column from users
    op.drop_index(op.f('ix_users_plan_tier'), table_name='users')
    op.drop_column('users', 'plan_tier')

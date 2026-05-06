"""
Add billing fields for Stripe integration

Revision ID: 009
Revises: 008
Create Date: 2026-02-11

BLOCK 7: Billing & Monetization Layer
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers
revision = '009'
down_revision = '008'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add Stripe billing fields to users table."""
    
    # Add billing columns to users table
    op.add_column(
        'users',
        sa.Column(
            'stripe_customer_id',
            sa.String(length=255),
            nullable=True,
            comment='Stripe customer ID for billing'
        )
    )
    
    op.add_column(
        'users',
        sa.Column(
            'stripe_subscription_id',
            sa.String(length=255),
            nullable=True,
            comment='Active Stripe subscription ID'
        )
    )
    
    op.add_column(
        'users',
        sa.Column(
            'subscription_status',
            sa.String(length=50),
            nullable=True,
            comment='Subscription status: active, canceled, past_due, etc.'
        )
    )
    
    op.add_column(
        'users',
        sa.Column(
            'current_period_end',
            sa.DateTime(timezone=True),
            nullable=True,
            comment='End of current billing period'
        )
    )
    
    # Create indexes for performance
    op.create_index(
        'idx_users_stripe_customer_id',
        'users',
        ['stripe_customer_id'],
        unique=False
    )
    
    op.create_index(
        'idx_users_stripe_subscription_id',
        'users',
        ['stripe_subscription_id'],
        unique=False
    )
    
    op.create_index(
        'idx_users_subscription_status',
        'users',
        ['subscription_status'],
        unique=False
    )


def downgrade() -> None:
    """Remove Stripe billing fields from users table."""
    
    # Drop indexes
    op.drop_index('idx_users_subscription_status', table_name='users')
    op.drop_index('idx_users_stripe_subscription_id', table_name='users')
    op.drop_index('idx_users_stripe_customer_id', table_name='users')
    
    # Drop columns
    op.drop_column('users', 'current_period_end')
    op.drop_column('users', 'subscription_status')
    op.drop_column('users', 'stripe_subscription_id')
    op.drop_column('users', 'stripe_customer_id')

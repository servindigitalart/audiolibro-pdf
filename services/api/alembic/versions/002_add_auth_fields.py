"""Add authentication fields to users table

Revision ID: 002_add_auth_fields
Revises: 001_initial
Create Date: 2026-02-11

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '002_add_auth_fields'
down_revision = '001_initial_setup'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add authentication and OAuth fields to users table."""
    
    # Remove full_name column (not needed in auth phase)
    op.drop_column('users', 'full_name')
    
    # Add authentication fields
    op.add_column('users', sa.Column('hashed_password', sa.String(255), nullable=True))
    op.add_column('users', sa.Column('is_verified', sa.Boolean(), nullable=False, server_default='false'))
    op.add_column('users', sa.Column('role', sa.String(50), nullable=False, server_default='user'))
    
    # Add OAuth fields
    op.add_column('users', sa.Column('oauth_provider', sa.String(50), nullable=True))
    op.add_column('users', sa.Column('oauth_id', sa.String(255), nullable=True))
    
    # Create indexes for performance
    op.create_index('ix_users_role', 'users', ['role'])
    op.create_index('ix_users_oauth_provider', 'users', ['oauth_provider'])
    op.create_index('ix_users_oauth_id', 'users', ['oauth_id'])
    
    # Create unique constraint for OAuth provider + ID combination
    op.create_index(
        'ix_users_oauth_provider_id',
        'users',
        ['oauth_provider', 'oauth_id'],
        unique=True,
        postgresql_where=sa.text("oauth_provider IS NOT NULL AND oauth_id IS NOT NULL")
    )


def downgrade() -> None:
    """Revert authentication and OAuth fields."""
    
    # Drop indexes
    op.drop_index('ix_users_oauth_provider_id', table_name='users')
    op.drop_index('ix_users_oauth_id', table_name='users')
    op.drop_index('ix_users_oauth_provider', table_name='users')
    op.drop_index('ix_users_role', table_name='users')
    
    # Drop columns
    op.drop_column('users', 'oauth_id')
    op.drop_column('users', 'oauth_provider')
    op.drop_column('users', 'role')
    op.drop_column('users', 'is_verified')
    op.drop_column('users', 'hashed_password')
    
    # Add back full_name column
    op.add_column('users', sa.Column('full_name', sa.String(255), nullable=True))

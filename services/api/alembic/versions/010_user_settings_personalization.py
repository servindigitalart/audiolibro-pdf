"""
Add user settings and personalization features

Revision ID: 010
Revises: 009
Create Date: 2026-02-11

BLOCK 8E: User Settings & Personalization Layer
- Add full_name field to users table
- Create api_keys table for API key management
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID
import uuid

# revision identifiers
revision = '010'
down_revision = '009'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add user personalization features."""
    
    # 1. Add full_name column to users table
    op.add_column(
        'users',
        sa.Column(
            'full_name',
            sa.String(length=255),
            nullable=True,
            comment='User full name for profile display'
        )
    )
    
    # 2. Create api_keys table
    op.create_table(
        'api_keys',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column('user_id', UUID(as_uuid=True), nullable=False),
        sa.Column('key_hash', sa.String(length=255), nullable=False, unique=True),
        sa.Column('key_preview', sa.String(length=10), nullable=False, comment='Last 4 chars for display'),
        sa.Column('is_active', sa.Boolean(), nullable=False, default=True, server_default='true'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('last_used_at', sa.DateTime(timezone=True), nullable=True),
        
        # Foreign key constraint
        sa.ForeignKeyConstraint(
            ['user_id'],
            ['users.id'],
            name='fk_api_keys_user_id',
            ondelete='CASCADE'
        ),
        
        # Primary key constraint
        sa.PrimaryKeyConstraint('id', name='pk_api_keys')
    )
    
    # 3. Create indexes for api_keys table
    op.create_index(
        'ix_api_keys_user_id_is_active',
        'api_keys',
        ['user_id', 'is_active'],
        unique=False
    )
    
    op.create_index(
        'ix_api_keys_key_hash',
        'api_keys',
        ['key_hash'],
        unique=True
    )


def downgrade() -> None:
    """Remove user personalization features."""
    
    # Drop api_keys table and indexes
    op.drop_index('ix_api_keys_key_hash', table_name='api_keys')
    op.drop_index('ix_api_keys_user_id_is_active', table_name='api_keys')
    op.drop_table('api_keys')
    
    # Remove full_name column from users table
    op.drop_column('users', 'full_name')

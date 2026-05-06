"""
API Key Model (BLOCK 8E)
=========================
API key management for programmatic access.
"""

from datetime import datetime
from typing import Optional
from uuid import UUID, uuid4

from sqlalchemy import String, DateTime, ForeignKey, func, Index
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class APIKey(Base):
    """
    API key for programmatic access.
    
    Attributes:
        id: Unique key identifier (UUID)
        user_id: Foreign key to user
        key_hash: Bcrypt hashed API key
        key_preview: Last 4 characters for display
        created_at: Key creation timestamp
        last_used_at: Last time key was used
        is_active: Whether key is active
    """

    __tablename__ = "api_keys"

    # Primary Key
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    
    # Foreign Key
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    
    # Key Data
    key_hash: Mapped[str] = mapped_column(
        String(255), nullable=False, unique=True, index=True
    )
    key_preview: Mapped[str] = mapped_column(
        String(10), nullable=False  # Last 4-6 chars for display
    )
    
    # Status
    is_active: Mapped[bool] = mapped_column(
        default=True, nullable=False, index=True
    )
    
    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    last_used_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    
    # Indexes for performance
    __table_args__ = (
        Index("ix_api_keys_user_active", "user_id", "is_active"),
    )

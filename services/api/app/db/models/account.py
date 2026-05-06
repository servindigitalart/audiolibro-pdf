"""
Account Models
==============
Account preferences and activity tracking models.
"""

from datetime import datetime
from typing import Optional
from uuid import UUID, uuid4

from sqlalchemy import String, DateTime, Boolean, Text, JSON, func, Index
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.postgresql import UUID as PGUUID

from app.db.session import Base


class AccountPreferences(Base):
    """
    User account preferences and settings.
    
    Stores user-specific configuration for the account experience.
    """
    
    __tablename__ = "account_preferences"
    
    # Primary Key
    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    
    # User Reference
    user_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        nullable=False,
        unique=True,
        index=True,
    )
    
    # Preferences
    preferred_language: Mapped[str] = mapped_column(
        String(10),
        nullable=False,
        default="en",
    )
    
    preferred_voice: Mapped[Optional[str]] = mapped_column(
        String(100),
        nullable=True,
    )
    
    timezone: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="UTC",
    )
    
    currency: Mapped[str] = mapped_column(
        String(3),
        nullable=False,
        default="USD",
    )
    
    # Notification Settings
    email_notifications: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
    )
    
    marketing_emails: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
    )
    
    usage_alerts: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
    )
    
    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
    
    def __repr__(self) -> str:
        return f"<AccountPreferences(user_id={self.user_id}, lang={self.preferred_language})>"


class UserActivityLog(Base):
    """
    User activity and audit log.
    
    Tracks all significant user actions for security and analytics.
    """
    
    __tablename__ = "user_activity_log"
    
    # Primary Key
    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    
    # User Reference
    user_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        nullable=False,
        index=True,
    )
    
    # Activity Details
    activity_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        index=True,
    )
    
    description: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )
    
    # Context
    ip_address: Mapped[Optional[str]] = mapped_column(
        String(45),  # IPv6 length
        nullable=True,
    )
    
    user_agent: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
    )
    
    # Metadata
    metadata: Mapped[Optional[dict]] = mapped_column(
        JSON,
        nullable=True,
    )
    
    # Security Flags
    is_suspicious: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
    )
    
    # Timestamp
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        index=True,
    )
    
    # Indexes for common queries
    __table_args__ = (
        Index("idx_user_activity_created", "user_id", "created_at"),
        Index("idx_activity_type_created", "activity_type", "created_at"),
        Index("idx_suspicious_activities", "is_suspicious", "created_at"),
    )
    
    def __repr__(self) -> str:
        return f"<UserActivityLog(user_id={self.user_id}, type={self.activity_type})>"

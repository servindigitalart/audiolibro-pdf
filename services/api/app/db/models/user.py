"""
User Model
==========
User model with full authentication support and financial tracking.
"""

from datetime import datetime
from typing import Optional, List
from uuid import UUID, uuid4

from sqlalchemy import String, DateTime, Boolean, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base


class User(Base):
    """
    User model with authentication and OAuth support.
    
    Attributes:
        id: Unique user identifier (UUID)
        email: User email address (unique, indexed)
        hashed_password: Bcrypt hashed password (nullable for OAuth users)
        is_active: Whether the user account is active
        is_verified: Whether the user's email is verified
        role: User role (user, admin, etc.)
        oauth_provider: OAuth provider name (google, github, etc.)
        oauth_id: OAuth provider's user ID
        created_at: Account creation timestamp
        updated_at: Last update timestamp
    """

    __tablename__ = "users"

    # Primary Key
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    
    # Authentication
    email: Mapped[str] = mapped_column(
        String(255), unique=True, index=True, nullable=False
    )
    hashed_password: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True  # Nullable for OAuth-only users
    )
    
    # Profile (BLOCK 8E)
    full_name: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True
    )
    
    # Account Status
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False
    )
    is_verified: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    
    # Authorization
    role: Mapped[str] = mapped_column(
        String(50), default="user", nullable=False, index=True
    )
    
    # Financial - Plan Tier
    plan_tier: Mapped[str] = mapped_column(
        String(20), default="FREE", nullable=False, index=True
    )
    
    # Billing - Stripe Integration (BLOCK 7)
    stripe_customer_id: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True, index=True
    )
    stripe_subscription_id: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True, index=True
    )
    subscription_status: Mapped[Optional[str]] = mapped_column(
        String(50), nullable=True, index=True
    )
    current_period_end: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    
    # OAuth Support
    oauth_provider: Mapped[Optional[str]] = mapped_column(
        String(50), nullable=True, index=True
    )
    oauth_id: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True, index=True
    )
    
    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), 
        server_default=func.now(), 
        onupdate=func.now(), 
        nullable=False
    )
    
    # Relationships
    cost_events: Mapped[List["CostEvent"]] = relationship(
        "CostEvent", back_populates="user", lazy="selectin"
    )
    usage_quota: Mapped[Optional["UsageQuota"]] = relationship(
        "UsageQuota", back_populates="user", uselist=False, lazy="selectin"
    )
    documents: Mapped[List["Document"]] = relationship(
        "Document", back_populates="user", lazy="selectin", cascade="all, delete-orphan"
    )
    processing_jobs: Mapped[List["ProcessingJob"]] = relationship(
        "ProcessingJob", back_populates="user", lazy="selectin", cascade="all, delete-orphan"
    )

    # Computed Properties (BLOCK 7)
    @property
    def is_subscribed(self) -> bool:
        """Check if user has an active subscription."""
        return self.subscription_status in ("active", "trialing")
    
    @property
    def subscription_active(self) -> bool:
        """Check if user's subscription is currently active."""
        return self.subscription_status == "active"
    
    @property
    def has_valid_subscription(self) -> bool:
        """Check if user has a valid paid subscription."""
        if self.plan_tier == "FREE":
            return False
        return self.is_subscribed

    def __repr__(self) -> str:
        return f"<User(id={self.id}, email={self.email}, role={self.role}, plan={self.plan_tier})>"

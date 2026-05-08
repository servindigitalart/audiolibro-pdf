"""
Cost Database Models
====================
Database models for cost tracking and financial operations.
"""

from datetime import datetime
from typing import Optional
from uuid import uuid4

from sqlalchemy import (
    Column,
    String,
    Integer,
    Float,
    DateTime,
    ForeignKey,
    Enum as SQLEnum,
    JSON,
    Index,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.db.session import Base
from app.financial.cost.cost_enums import CostEventType, CostProvider


class CostEvent(Base):
    """
    Cost event tracking table.
    
    Records all cost-generating events for financial visibility,
    quota enforcement, and billing preparation.
    """
    
    __tablename__ = "cost_events"
    
    # Primary Key
    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
        index=True,
    )
    
    # User Reference
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    
    # Event Details
    event_type = Column(
        SQLEnum(CostEventType),
        nullable=False,
        index=True,
    )
    
    provider = Column(
        SQLEnum(CostProvider),
        nullable=True,
        default=CostProvider.INTERNAL,
    )
    
    # Cost Calculation
    quantity = Column(
        Float,
        nullable=False,
        default=1.0,
        comment="Quantity of units (e.g., characters, API calls, GB)",
    )
    
    unit_cost = Column(
        Float,
        nullable=False,
        default=0.0,
        comment="Cost per unit in USD",
    )
    
    total_cost = Column(
        Float,
        nullable=False,
        default=0.0,
        comment="Total cost in USD (quantity * unit_cost)",
    )
    
    # Metadata
    activity_metadata = Column("metadata",
        JSON,
        nullable=True,
        comment="Additional context (job_id, file_name, etc.)",
    )
    
    # Timestamps
    created_at = Column(
        DateTime,
        nullable=False,
        default=datetime.utcnow,
        index=True,
    )
    
    # Relationships
    user = relationship("User", back_populates="cost_events")
    
    # Indexes for common queries
    __table_args__ = (
        Index("idx_user_created", "user_id", "created_at"),
        Index("idx_event_type_created", "event_type", "created_at"),
        Index("idx_provider_created", "provider", "created_at"),
    )
    
    def __repr__(self) -> str:
        return (
            f"<CostEvent(id={self.id}, "
            f"user_id={self.user_id}, "
            f"event_type={self.event_type}, "
            f"total_cost=${self.total_cost:.4f})>"
        )
    
    @property
    def cost_usd(self) -> str:
        """Format cost as USD string."""
        return f"${self.total_cost:.2f}"


class UsageQuota(Base):
    """
    User usage quota tracking.
    
    Tracks monthly usage against plan limits.
    Resets on billing cycle.
    """
    
    __tablename__ = "usage_quotas"
    
    # Primary Key
    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    
    # User Reference
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    
    # Current Period
    period_start = Column(
        DateTime,
        nullable=False,
        default=datetime.utcnow,
    )
    
    period_end = Column(
        DateTime,
        nullable=False,
    )
    
    # Usage Tracking
    characters_used = Column(
        Integer,
        nullable=False,
        default=0,
        comment="Total characters processed this period",
    )
    
    jobs_created = Column(
        Integer,
        nullable=False,
        default=0,
        comment="Total jobs created this period",
    )
    
    storage_used_mb = Column(
        Float,
        nullable=False,
        default=0.0,
        comment="Current storage usage in MB",
    )
    
    api_calls = Column(
        Integer,
        nullable=False,
        default=0,
        comment="Total API calls this period",
    )
    
    # Timestamps
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(
        DateTime,
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )
    
    # Relationships
    user = relationship("User", back_populates="usage_quota")
    
    def __repr__(self) -> str:
        return (
            f"<UsageQuota(user_id={self.user_id}, "
            f"characters={self.characters_used}, "
            f"jobs={self.jobs_created})>"
        )

"""
Cost Database Models
====================
Database models for cost tracking and financial operations.
"""

from datetime import datetime
from typing import Optional
from uuid import uuid4

from sqlalchemy import (
    Boolean,
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
    #
    # native_enum=False + values_callable: same fix as migrations 012 and 014.
    # asyncpg sends enum member .name ("TTS_CHARACTERS") through the native codec
    # instead of .value ("tts_characters"), causing InvalidTextRepresentationError.
    # Storing as VARCHAR(50) bypasses the native codec entirely.
    # Migration 016 converts both columns from PostgreSQL ENUM to VARCHAR(50).
    event_type = Column(
        SQLEnum(CostEventType, native_enum=False, values_callable=lambda obj: [e.value for e in obj]),
        nullable=False,
        index=True,
    )

    provider = Column(
        SQLEnum(CostProvider, native_enum=False, values_callable=lambda obj: [e.value for e in obj]),
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
    
    # CALCULATED provider cost — quantity × the provider's published per-unit
    # rate.  This is NOT an invoice amount: Google Cloud TTS bills per character
    # against a published rate and exposes no per-request charge, so a true
    # `actual_invoice_cost` does not exist for us to store.  Do not present this
    # figure as billed spend; it is our own arithmetic on published rates.
    total_cost = Column(
        Float,
        nullable=False,
        default=0.0,
        comment="Calculated provider cost in USD (quantity * unit_cost) — not an invoice amount",
    )

    # ── Attribution (migration 031) ──────────────────────────────────────────
    # Previously only reachable by digging through the metadata JSON, which made
    # per-document and per-job cost queries impossible to index or aggregate.
    document_id = Column(
        UUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="Document this cost belongs to, when applicable",
    )
    job_id = Column(
        UUID(as_uuid=True),
        ForeignKey("processing_jobs.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="Processing job this cost belongs to, when applicable",
    )
    voice_id = Column(
        String(255),
        nullable=True,
        comment="TTS voice used, for per-voice cost attribution",
    )

    # ── Outcome (migration 031) ──────────────────────────────────────────────
    # A failed provider attempt is recorded with success=False and total_cost=0:
    # Google does not bill failed requests, and inventing a charge would be
    # dishonest.  The row exists so failed work stays *countable* even though it
    # is not chargeable.
    success = Column(
        Boolean,
        nullable=False,
        default=True,
        server_default="true",
        comment="True when the provider call succeeded, False when it failed",
    )
    failure_reason = Column(
        String(255),
        nullable=True,
        comment="Exception class name when success is 'false'",
    )
    attempt_number = Column(
        Integer,
        nullable=False,
        default=1,
        server_default="1",
        comment="Provider attempt for this logical chunk (1 = first try, >1 = retry)",
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
        # Drives the failed-spend and retry reports (migration 031).  Declared
        # here too, or metadata.create_all() — which builds the test schema —
        # would produce a database the migration chain never agrees with.
        Index("idx_cost_events_success_created", "success", "created_at"),
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

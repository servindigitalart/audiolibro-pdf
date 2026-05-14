"""
Billing Engine — SQLAlchemy Models
====================================
Tables added by migration 011_billing_engine.py.

All user_id FKs reference users.id (UUID).  Tables are append-only where
possible to preserve audit trails; hard deletes are never performed.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base


class SubscriptionAuditLog(Base):
    """Immutable record of every subscription state transition."""

    __tablename__ = "subscription_audit_log"

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    from_status: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    to_status: Mapped[str] = mapped_column(String(30), nullable=False)
    reason: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    actor: Mapped[str] = mapped_column(String(50), nullable=False, default="system")
    stripe_event_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )

    __table_args__ = (
        Index("ix_audit_log_user_created", "user_id", "created_at"),
    )


class UsageAggregate(Base):
    """
    Persistent daily/monthly usage rollups.

    The hot path writes to Redis; a background job (or request teardown)
    upserts into this table so usage survives Redis eviction.
    """

    __tablename__ = "usage_aggregate"

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    period_type: Mapped[str] = mapped_column(String(10), nullable=False)  # "day" | "month"
    period_key: Mapped[str] = mapped_column(String(10), nullable=False)   # "YYYY-MM-DD" | "YYYY-MM"
    api_calls: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    compute_ms: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    cost_usd: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("user_id", "period_type", "period_key", name="uq_usage_aggregate_period"),
        Index("ix_usage_aggregate_user_period", "user_id", "period_type", "period_key"),
    )


class IdempotencyKey(Base):
    """
    Two-phase idempotency guard: LOCKED → COMPLETE.

    A row is inserted with status=LOCKED before the operation.
    On success the response payload is stored and status flipped to COMPLETE.
    Any retry that finds a COMPLETE row returns the stored response immediately.
    A retry that finds a LOCKED row waits (handled at the service layer).
    """

    __tablename__ = "idempotency_keys"

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    idempotency_key: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="locked")  # locked | complete
    request_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    response_payload: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    response_status_code: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True, index=True)


class WebhookEvent(Base):
    """
    Persisted record of every inbound webhook event.
    Used for idempotency (deduplicate by stripe_event_id) and replay safety.
    """

    __tablename__ = "webhook_events"

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    stripe_event_id: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    payload: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")  # pending | processed | failed | replayed
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    processed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )

    __table_args__ = (
        Index("ix_webhook_events_type_status", "event_type", "status"),
    )

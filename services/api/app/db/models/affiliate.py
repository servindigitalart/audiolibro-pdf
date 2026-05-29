"""
Affiliate / Referral Models
============================
Lightweight referral tracking for the Sonoro affiliate program.

Design:
  - Affiliate: a creator/promoter with a unique referral slug
  - AffiliateClick: every tracked link visit (privacy-safe hashes only)
  - AffiliateConversion: paid subscription triggered by a referral

Idempotency:
  AffiliateConversion.stripe_event_id is UNIQUE — double-processing
  the same Stripe webhook is safe.

Payouts:
  Tracked internally (status: pending → approved → paid).
  No Stripe Connect yet — manual payout workflow.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean, Column, DateTime, Float, ForeignKey, Index, String,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.db.session import Base


class Affiliate(Base):
    """Creator/promoter who earns commission on referred paying subscribers."""

    __tablename__ = "affiliates"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # The affiliate may or may not also be a Sonoro user
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    name  = Column(String(200), nullable=False)
    email = Column(String(255), nullable=False, index=True)

    # URL-safe code: letters/digits/hyphens, 3–50 chars, globally unique
    slug  = Column(String(50), unique=True, nullable=False, index=True)

    # pending → active → paused (we manually activate)
    status = Column(String(20), nullable=False, default="pending")

    # Commission rate applied to the first successful charge (% of gross)
    commission_rate_pct = Column(Float, nullable=False, default=20.0)

    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    clicks      = relationship("AffiliateClick",      back_populates="affiliate", cascade="all, delete-orphan")
    conversions = relationship("AffiliateConversion", back_populates="affiliate", cascade="all, delete-orphan")

    __table_args__ = (
        Index("idx_affiliates_slug",   "slug"),
        Index("idx_affiliates_status", "status"),
    )

    def __repr__(self) -> str:
        return f"<Affiliate(slug={self.slug!r}, status={self.status!r})>"


class AffiliateClick(Base):
    """One tracked visit via an affiliate link."""

    __tablename__ = "affiliate_clicks"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    affiliate_id = Column(
        UUID(as_uuid=True),
        ForeignKey("affiliates.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Anonymous visitor identifier (set by the client, e.g. a random localStorage UUID)
    visitor_id   = Column(String(64),  nullable=True)
    landing_path = Column(String(500), nullable=True)

    # Privacy-safe fingerprint components (SHA-256 hashed, never raw)
    user_agent_hash = Column(String(64), nullable=True)
    ip_hash         = Column(String(64), nullable=True)

    # Filled in when the visitor later creates an account
    converted_to_signup = Column(Boolean, nullable=False, default=False)
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)

    # Relationships
    affiliate = relationship("Affiliate", back_populates="clicks")

    __table_args__ = (
        Index("idx_affiliate_clicks_affiliate_created", "affiliate_id", "created_at"),
        Index("idx_affiliate_clicks_visitor",           "visitor_id"),
    )


class AffiliateConversion(Base):
    """
    A referred user completed a paid Stripe checkout.

    stripe_event_id is the idempotency key — processing the same
    checkout.session.completed event twice results in an IntegrityError
    on this column, which the caller should catch and ignore.
    """

    __tablename__ = "affiliate_conversions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    affiliate_id = Column(
        UUID(as_uuid=True),
        ForeignKey("affiliates.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    referred_user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # Stripe identifiers for cross-reference
    stripe_customer_id     = Column(String(100), nullable=True)
    stripe_subscription_id = Column(String(100), nullable=True)

    # Idempotency — one row per Stripe event
    stripe_event_id = Column(String(200), unique=True, nullable=False, index=True)

    plan_tier  = Column(String(20), nullable=False)
    amount_usd = Column(Float, nullable=False)             # gross charge amount

    # Commission snapshot (locked at time of conversion)
    commission_pct        = Column(Float, nullable=False)
    commission_amount_usd = Column(Float, nullable=False)

    # pending → approved → paid  |  pending → reversed
    status = Column(String(20), nullable=False, default="pending")

    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    affiliate = relationship("Affiliate", back_populates="conversions")

    __table_args__ = (
        Index("idx_affiliate_conversions_affiliate_created", "affiliate_id", "created_at"),
        Index("idx_affiliate_conversions_status",            "status"),
    )

    def __repr__(self) -> str:
        return (
            f"<AffiliateConversion(affiliate_id={self.affiliate_id}, "
            f"status={self.status!r}, commission=${self.commission_amount_usd:.2f})>"
        )

"""
Analytics Models
================
Lightweight behavioral analytics for understanding retention, listening
patterns, and conversion triggers.

Design principles:
  - No PII beyond user_id FK
  - Nullable FKs where possible to survive document/user deletion
  - JSON properties for flexible metadata (no schema migrations on every event)
  - Separate PlaybackSession (rich listening data) from AnalyticsEvent (sparse signals)
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    Index,
    Integer,
    JSON,
    String,
    ForeignKey,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.db.session import Base


class PlaybackSession(Base):
    """
    One continuous listening session.

    Created when a user starts or resumes playback; updated when they
    pause, navigate away, or reach completion.  The frontend holds the
    session_id and sends a PATCH when the session ends so we get accurate
    listened_seconds even for partial listens.
    """

    __tablename__ = "playback_sessions"

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        index=True,
    )

    # Who and what
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    document_id = Column(
        UUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # Timing
    started_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    ended_at   = Column(DateTime, nullable=True)

    # Listening metrics
    listened_seconds     = Column(Integer, nullable=False, default=0, server_default="0")
    completion_percentage = Column(Float,   nullable=False, default=0.0, server_default="0")
    playback_speed       = Column(Float,   nullable=False, default=1.0, server_default="1")

    # Engagement signals
    chapters_visited = Column(
        JSON,
        nullable=False,
        default=list,
        server_default=text("'[]'::json"),
        comment="Ordered list of chapter indices visited during this session",
    )
    resumed_from_continue_listening = Column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
    )
    session_source = Column(
        String(50),
        nullable=True,
        comment="direct | continue_listening | autoplay",
    )

    # Relationships
    user     = relationship("User",     foreign_keys=[user_id])
    document = relationship("Document", foreign_keys=[document_id])
    events   = relationship("AnalyticsEvent", back_populates="session", cascade="all, delete-orphan")

    __table_args__ = (
        Index("idx_playback_sessions_user_started", "user_id", "started_at"),
        Index("idx_playback_sessions_document", "document_id"),
    )

    def __init__(self, **kwargs):
        kwargs.setdefault("listened_seconds", 0)
        kwargs.setdefault("completion_percentage", 0.0)
        kwargs.setdefault("playback_speed", 1.0)
        kwargs.setdefault("resumed_from_continue_listening", False)
        super().__init__(**kwargs)

    @property
    def duration_seconds(self) -> float | None:
        if self.started_at and self.ended_at:
            return (self.ended_at - self.started_at).total_seconds()
        return None


class AnalyticsEvent(Base):
    """
    Sparse product analytics event.

    Used for: paywall views, upgrade clicks, voice previews, completion
    signals, chapter skips — anything that doesn't fit neatly into a
    PlaybackSession but is valuable for conversion/retention analysis.

    user_id is nullable so pre-auth funnel events (pricing page) can be
    stored without a user row.
    """

    __tablename__ = "analytics_events"

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        index=True,
    )

    # Actor
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # Event descriptor
    event_type = Column(String(64), nullable=False, index=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)

    # Flexible payload — validated and sanitised at ingestion time
    properties = Column(
        JSON,
        nullable=False,
        default=dict,
        server_default=text("'{}'::json"),
    )

    # Optional context links
    session_id = Column(
        UUID(as_uuid=True),
        ForeignKey("playback_sessions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    document_id = Column(
        UUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Relationships
    user    = relationship("User",            foreign_keys=[user_id])
    session = relationship("PlaybackSession", back_populates="events", foreign_keys=[session_id])

    __table_args__ = (
        Index("idx_analytics_events_user_created",  "user_id",    "created_at"),
        Index("idx_analytics_events_type_created",  "event_type", "created_at"),
    )

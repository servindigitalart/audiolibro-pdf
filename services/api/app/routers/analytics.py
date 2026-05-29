"""
Analytics Router (user-facing)
==============================
Endpoints for behavioral event ingestion and playback session management.

Design:
  - Events are stored to DB for aggregation (unlike /events which logs only)
  - All endpoints return 200/202 even on internal failure — analytics must
    never interrupt the user experience
  - Sensitive property keys are stripped at ingestion
  - Auth required — user_id sourced from JWT, never trusted from client
"""
from __future__ import annotations

import logging
from typing import Any, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth_dependencies import get_current_active_user
from app.db.models.user import User
from app.db.session import get_async_db as get_db
from app.analytics.analytics_service import AnalyticsService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/analytics", tags=["analytics"])

# Valid behavioral event types for DB persistence
_VALID_DB_EVENTS = frozenset({
    "audiobook_started",
    "audiobook_completed",
    "playback_paused",
    "playback_resumed",
    "chapter_changed",
    "voice_preview_played",
    "paywall_viewed",
    "paywall_dismissed",
    "upgrade_clicked",
    "continue_listening_opened",
    "player_opened",
    "audiobook_downloaded",
})


# ── Request / Response schemas ────────────────────────────────────────────────

class EventRequest(BaseModel):
    event_type:  str                           = Field(..., max_length=64)
    properties:  Optional[dict[str, Any]]      = Field(default_factory=dict)
    document_id: Optional[str]                 = Field(default=None)
    session_id:  Optional[str]                 = Field(default=None)


class SessionStartRequest(BaseModel):
    document_id:                   Optional[str]  = Field(default=None)
    source:                        str             = Field(default="direct", max_length=50)
    resumed_from_continue_listening: bool          = Field(default=False)


class SessionEndRequest(BaseModel):
    listened_seconds:      int    = Field(default=0, ge=0)
    completion_percentage: float  = Field(default=0.0, ge=0.0, le=100.0)
    playback_speed:        float  = Field(default=1.0, ge=0.25, le=4.0)
    chapters_visited:      list[int] = Field(default_factory=list)


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/events", status_code=202)
async def record_event(
    payload:      EventRequest,
    current_user: User          = Depends(get_current_active_user),
    db:           AsyncSession  = Depends(get_db),
) -> dict:
    """
    Persist a behavioral analytics event to the DB.

    Accepts known event types only; unknown events are accepted but logged
    as a warning.  Returns 202 even if the DB write fails.
    """
    if payload.event_type not in _VALID_DB_EVENTS:
        logger.warning(
            "[SONORO] analytics_unknown_event_type event_type=%s user_id=%s",
            payload.event_type, current_user.id,
        )

    doc_id: Optional[UUID] = None
    if payload.document_id:
        try:
            doc_id = UUID(payload.document_id)
        except ValueError:
            pass

    sess_id: Optional[UUID] = None
    if payload.session_id:
        try:
            sess_id = UUID(payload.session_id)
        except ValueError:
            pass

    await AnalyticsService.record_event(
        db=db,
        user_id=current_user.id,
        event_type=payload.event_type,
        properties=payload.properties or {},
        document_id=doc_id,
        session_id=sess_id,
    )

    return {"accepted": True}


@router.post("/sessions", status_code=201)
async def start_session(
    payload:      SessionStartRequest,
    current_user: User               = Depends(get_current_active_user),
    db:           AsyncSession       = Depends(get_db),
) -> dict:
    """
    Start a new playback session.  Returns the session_id for the frontend
    to use when ending the session.

    Returns session_id=null if the DB write fails — the frontend should
    handle a null session_id gracefully (skip end-session call).
    """
    doc_id: Optional[UUID] = None
    if payload.document_id:
        try:
            doc_id = UUID(payload.document_id)
        except ValueError:
            pass

    source = payload.source if payload.source in ("direct", "continue_listening", "autoplay") else "direct"

    session_id = await AnalyticsService.start_session(
        db=db,
        user_id=current_user.id,
        document_id=doc_id,
        source=source,
        resumed_from_continue_listening=payload.resumed_from_continue_listening,
    )

    return {"session_id": session_id}


@router.patch("/sessions/{session_id}", status_code=200)
async def end_session(
    session_id:   str,
    payload:      SessionEndRequest,
    current_user: User              = Depends(get_current_active_user),
    db:           AsyncSession      = Depends(get_db),
) -> dict:
    """
    End a playback session with final listening metrics.

    Always returns 200 — if the session_id is invalid or the DB write
    fails, the error is logged but not surfaced to the client.
    """
    try:
        sess_uuid = UUID(session_id)
    except ValueError:
        return {"updated": False, "reason": "invalid_session_id"}

    await AnalyticsService.end_session(
        db=db,
        session_id=sess_uuid,
        listened_seconds=payload.listened_seconds,
        completion_percentage=payload.completion_percentage,
        playback_speed=payload.playback_speed,
        chapters_visited=payload.chapters_visited,
    )

    return {"updated": True}

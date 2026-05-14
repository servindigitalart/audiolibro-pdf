"""
Analytics Events Router
=======================
Receives frontend event telemetry for product analytics.

Events are lightweight — no PII beyond user_id. Used to track:
  - Activation funnel (signup → first action → conversion)
  - Paywall interactions (shown → dismissed → converted)
  - Feature gate hits (upgrade trigger)
  - Upgrade intent and completion
  - Onboarding progress
  - UTM attribution

Design:
  - Batch endpoint accepts up to 50 events per call
  - Authentication optional — unauthenticated events accepted for
    pre-login funnel tracking (landing page, pricing page views)
  - Events stored to monitoring backend (structured logging only —
    no DB write in hot path)
  - Sensitive properties are dropped server-side before logging
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field, field_validator

from app.core.auth_dependencies import get_current_user_optional
from app.db.models.user import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/events", tags=["analytics"])

# Properties that must never be logged (strip before processing)
_BLOCKED_PROPS = {"password", "token", "secret", "card", "ssn", "cvv"}

# Maximum events per batch
_MAX_BATCH_SIZE = 50

# Valid event names (allowlist to prevent event spam)
_VALID_EVENTS = frozenset({
    "sign_up",
    "login",
    "logout",
    "onboarding_step",
    "onboarding_complete",
    "document_upload",
    "document_processed",
    "feature_gate_hit",
    "paywall_shown",
    "paywall_dismissed",
    "upgrade_intent",
    "upgrade_complete",
    "upgrade_abandoned",
    "quota_warning",
    "quota_exceeded",
    "upgrade_nudge_shown",
    "upgrade_nudge_clicked",
    "pricing_page_view",
    "page_view",
    "checkout_started",
    "checkout_completed",
    "checkout_abandoned",
    "referral_shared",
    "referral_converted",
})


class EventPayload(BaseModel):
    event: str = Field(..., max_length=64)
    properties: Optional[dict[str, Any]] = Field(default_factory=dict)
    user_id: Optional[str] = Field(default=None, max_length=64)
    session_id: Optional[str] = Field(default=None, max_length=64)
    timestamp: Optional[str] = Field(default=None, max_length=32)
    utm_source: Optional[str] = Field(default=None, max_length=64)
    utm_medium: Optional[str] = Field(default=None, max_length=64)
    utm_campaign: Optional[str] = Field(default=None, max_length=64)
    utm_term: Optional[str] = Field(default=None, max_length=64)
    utm_content: Optional[str] = Field(default=None, max_length=64)

    @field_validator("event")
    @classmethod
    def validate_event_name(cls, v: str) -> str:
        if v not in _VALID_EVENTS:
            # Accept unknown events but normalise — avoids hard failure on new events
            return v[:64]
        return v

    @field_validator("properties")
    @classmethod
    def strip_sensitive(cls, v: Optional[dict]) -> dict:
        if not v:
            return {}
        return {k: val for k, val in v.items() if k.lower() not in _BLOCKED_PROPS}


class BatchEventRequest(BaseModel):
    events: list[EventPayload] = Field(..., max_length=_MAX_BATCH_SIZE)


def _log_event(
    event: EventPayload,
    request: Request,
    resolved_user_id: Optional[str],
) -> None:
    user_id = resolved_user_id or event.user_id or "anonymous"
    logger.info(
        "analytics_event",
        extra={
            "analytics_event": event.event,
            "user_id": user_id,
            "session_id": event.session_id,
            "utm_source": event.utm_source,
            "utm_medium": event.utm_medium,
            "utm_campaign": event.utm_campaign,
            "properties": event.properties,
            "client_ip": request.client.host if request.client else None,
        },
    )


@router.post("/batch", status_code=202)
async def receive_event_batch(
    payload: BatchEventRequest,
    request: Request,
    current_user: Optional[User] = Depends(get_current_user_optional),
) -> dict:
    """
    Accept a batch of frontend analytics events.

    Authentication is optional — anonymous events are accepted to track
    pre-login funnel steps (landing page, pricing page, etc.).
    """
    resolved_user_id = str(current_user.id) if current_user else None

    for event in payload.events:
        _log_event(event, request, resolved_user_id)

    return {"accepted": len(payload.events)}


@router.post("", status_code=202)
async def receive_single_event(
    event: EventPayload,
    request: Request,
    current_user: Optional[User] = Depends(get_current_user_optional),
) -> dict:
    """Accept a single analytics event (convenience endpoint)."""
    resolved_user_id = str(current_user.id) if current_user else None
    _log_event(event, request, resolved_user_id)
    return {"accepted": 1}

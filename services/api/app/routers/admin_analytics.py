"""
Admin Analytics Router
======================
Internal visibility into behavioral analytics, retention, and conversion.

All endpoints are admin-only and return aggregate data only — no PII.
"""
from __future__ import annotations

import logging
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth_dependencies import require_admin
from app.db.models.user import User
from app.db.session import get_async_db as get_db
from app.analytics.analytics_service import AnalyticsService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/admin/analytics", tags=["admin", "analytics"])


@router.get("/overview")
async def get_analytics_overview(
    days: int              = Query(default=30, ge=1, le=365),
    current_user: User     = Depends(require_admin),
    db: AsyncSession       = Depends(get_db),
):
    """
    Combined analytics overview: completion, sessions, events, upgrades.

    **Admin only**
    """
    completion    = await AnalyticsService.get_completion_stats(db, days=days)
    sessions      = await AnalyticsService.get_session_summary(db, days=days)
    top_events    = await AnalyticsService.get_top_events(db, days=days)
    upgrades      = await AnalyticsService.get_upgrade_triggers(db, days=days)
    retention     = await AnalyticsService.get_retention_signals(db)

    logger.info(
        "admin_analytics_overview_accessed admin_id=%s days=%d",
        current_user.id, days,
    )

    return {
        "period_days":      days,
        "completion":       completion,
        "sessions":         sessions,
        "top_events":       top_events,
        "upgrade_funnel":   upgrades,
        "retention":        retention,
        "accessed_by":      current_user.email,
        "accessed_at":      datetime.utcnow().isoformat(),
    }


@router.get("/completion-stats")
async def get_completion_stats(
    days: int          = Query(default=30, ge=1, le=365),
    current_user: User = Depends(require_admin),
    db: AsyncSession   = Depends(get_db),
):
    """
    Listening completion rates: engaged (>10%), halfway (>50%), completed (>90%).

    **Admin only**

    Key KPI: what % of sessions result in the user finishing the audiobook?
    """
    stats = await AnalyticsService.get_completion_stats(db, days=days)
    logger.info("admin_completion_stats_accessed admin_id=%s", current_user.id)
    return {**stats, "accessed_by": current_user.email, "accessed_at": datetime.utcnow().isoformat()}


@router.get("/session-summary")
async def get_session_summary(
    days: int          = Query(default=30, ge=1, le=365),
    current_user: User = Depends(require_admin),
    db: AsyncSession   = Depends(get_db),
):
    """
    Session-level aggregate: duration, speed, continue-listening resume rate.

    **Admin only**
    """
    summary = await AnalyticsService.get_session_summary(db, days=days)
    return {**summary, "accessed_by": current_user.email, "accessed_at": datetime.utcnow().isoformat()}


@router.get("/top-events")
async def get_top_events(
    days: int          = Query(default=30, ge=1, le=365),
    current_user: User = Depends(require_admin),
    db: AsyncSession   = Depends(get_db),
):
    """
    Most common analytics event types in the lookback window.

    **Admin only**

    Useful for understanding which product features are being used.
    """
    events = await AnalyticsService.get_top_events(db, days=days)
    return {
        "period_days": days,
        "events": events,
        "accessed_by": current_user.email,
        "accessed_at": datetime.utcnow().isoformat(),
    }


@router.get("/upgrade-triggers")
async def get_upgrade_triggers(
    days: int          = Query(default=90, ge=1, le=365),
    current_user: User = Depends(require_admin),
    db: AsyncSession   = Depends(get_db),
):
    """
    Paywall → upgrade click → conversion funnel.

    **Admin only**

    Answers: "What % of users who see the paywall click Upgrade?
              What % of those actually complete checkout?"
    """
    triggers = await AnalyticsService.get_upgrade_triggers(db, days=days)
    return {**triggers, "accessed_by": current_user.email, "accessed_at": datetime.utcnow().isoformat()}


@router.get("/retention")
async def get_retention(
    current_user: User = Depends(require_admin),
    db: AsyncSession   = Depends(get_db),
):
    """
    Multi-session retention: how many users come back for a second session?

    **Admin only**

    returning_users / total_users = day-1+ retention rate.
    """
    retention = await AnalyticsService.get_retention_signals(db)
    return {**retention, "accessed_by": current_user.email, "accessed_at": datetime.utcnow().isoformat()}


@router.get("/voice-engagement")
async def get_voice_engagement(
    days: int          = Query(default=30, ge=1, le=365),
    current_user: User = Depends(require_admin),
    db: AsyncSession   = Depends(get_db),
):
    """
    Top previewed voices from voice_preview_played events.

    **Admin only**

    Answers: "Which voices generate the most interest? Does voice preview
              correlate with conversion?"
    """
    voices = await AnalyticsService.get_voice_engagement(db, days=days)
    return {
        "period_days": days,
        "voices": voices,
        "accessed_by": current_user.email,
        "accessed_at": datetime.utcnow().isoformat(),
    }

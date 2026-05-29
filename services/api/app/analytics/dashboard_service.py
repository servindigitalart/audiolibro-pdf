"""
Dashboard Service
=================
Aggregation logic for the admin intelligence dashboard.

All methods are read-only and return serialisable dicts.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.analytics import AnalyticsEvent, PlaybackSession
from app.db.models.processing_job import ProcessingJob
from app.db.models.user import User
from app.pricing.tiers import TIER_CATALOG, PlanTier

logger = logging.getLogger(__name__)

_PLAN_PRICES: dict[str, float] = {
    t.value: cfg.monthly_price_usd for t, cfg in TIER_CATALOG.items()
}

_ACTIVITY_LABELS: dict[str, str] = {
    "audiobook_started":         "Audiobook started",
    "audiobook_completed":       "Audiobook completed",
    "paywall_viewed":            "Paywall viewed",
    "paywall_dismissed":         "Paywall dismissed",
    "upgrade_clicked":           "Upgrade CTA clicked",
    "voice_preview_played":      "Voice preview played",
    "continue_listening_opened": "Continue listening opened",
    "player_opened":             "Player opened",
    "audiobook_downloaded":      "Audiobook downloaded",
    "quota_exceeded":            "Quota limit reached",
    "playback_paused":           "Playback paused",
    "playback_resumed":          "Playback resumed",
    "chapter_changed":           "Chapter changed",
}

_SENSITIVE_PROPS = {"password", "token", "secret", "card", "ssn", "cvv"}


def _activity_severity(event_type: str) -> str:
    if event_type == "quota_exceeded":
        return "warning"
    if event_type in ("audiobook_completed", "upgrade_clicked", "audiobook_downloaded"):
        return "success"
    if event_type == "paywall_viewed":
        return "info"
    return "neutral"


def _strip_props(props: dict[str, Any] | None) -> dict[str, Any]:
    if not props:
        return {}
    return {k: v for k, v in props.items() if k.lower() not in _SENSITIVE_PROPS}


class DashboardService:

    @staticmethod
    async def get_kpis(db: AsyncSession) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        cut7  = now - timedelta(days=7)
        cut30 = now - timedelta(days=30)

        # ── Users ──────────────────────────────────────────────────────────────
        total = await db.scalar(select(func.count(User.id))) or 0

        active_7d = await db.scalar(
            select(func.count(func.distinct(AnalyticsEvent.user_id)))
            .where(AnalyticsEvent.created_at >= cut7)
            .where(AnalyticsEvent.user_id.isnot(None))
        ) or 0

        active_30d = await db.scalar(
            select(func.count(func.distinct(AnalyticsEvent.user_id)))
            .where(AnalyticsEvent.created_at >= cut30)
            .where(AnalyticsEvent.user_id.isnot(None))
        ) or 0

        plan_rows = (await db.execute(
            select(User.plan_tier, func.count(User.id))
            .where(User.is_active.is_(True))
            .group_by(User.plan_tier)
        )).all()

        by_plan: dict[str, int] = {}
        for row in plan_rows:
            by_plan[(row[0] or "FREE").upper()] = row[1]

        paid  = sum(n for t, n in by_plan.items() if t != "FREE")
        free  = by_plan.get("FREE", 0)

        # ── Revenue (estimated from plan distribution) ─────────────────────────
        mrr   = sum(n * _PLAN_PRICES.get(t, 0.0) for t, n in by_plan.items())
        arr   = mrr * 12
        arpu  = mrr / total if total > 0 else 0.0
        arppu = mrr / paid  if paid  > 0 else 0.0

        # ── Costs (30d job telemetry) ──────────────────────────────────────────
        monthly_cost = float(await db.scalar(
            select(func.sum(ProcessingJob.estimated_cost_usd))
            .where(ProcessingJob.created_at >= cut30)
            .where(ProcessingJob.estimated_cost_usd.isnot(None))
        ) or 0.0)

        margin_pct = ((mrr - monthly_cost) / mrr * 100) if mrr > 0 else 0.0

        # ── Content ────────────────────────────────────────────────────────────
        audiobooks = await db.scalar(
            select(func.count(ProcessingJob.id))
            .where(ProcessingJob.status == "completed")
        ) or 0

        ls = (await db.execute(
            select(
                func.sum(PlaybackSession.listened_seconds),
                func.avg(PlaybackSession.completion_percentage),
                func.avg(PlaybackSession.listened_seconds),
            )
        )).one()

        total_secs  = float(ls[0] or 0)
        avg_compl   = float(ls[1] or 0.0)
        avg_sess_s  = float(ls[2] or 0.0)

        # ── Conversion (30d) ───────────────────────────────────────────────────
        quota_exceeded = await db.scalar(
            select(func.count(AnalyticsEvent.id))
            .where(AnalyticsEvent.event_type == "quota_exceeded")
            .where(AnalyticsEvent.created_at >= cut30)
        ) or 0

        paywall_views = await db.scalar(
            select(func.count(AnalyticsEvent.id))
            .where(AnalyticsEvent.event_type == "paywall_viewed")
            .where(AnalyticsEvent.created_at >= cut30)
        ) or 0

        upgrades = await db.scalar(
            select(func.count(AnalyticsEvent.id))
            .where(AnalyticsEvent.event_type == "upgrade_clicked")
            .where(AnalyticsEvent.created_at >= cut30)
        ) or 0

        conv_rate = (upgrades / paywall_views * 100) if paywall_views > 0 else 0.0

        return {
            "generated_at": now.isoformat(),
            "users": {
                "total": total,
                "active_7d": active_7d,
                "active_30d": active_30d,
                "free": free,
                "paid": paid,
                "by_plan": by_plan,
            },
            "revenue": {
                "mrr_usd":           round(mrr, 2),
                "arr_projected_usd": round(arr, 2),
                "arpu_usd":          round(arpu, 2),
                "arppu_usd":         round(arppu, 2),
            },
            "costs": {
                "monthly_estimated_usd":     round(monthly_cost, 4),
                "estimated_gross_margin_pct": round(margin_pct, 1),
            },
            "content": {
                "audiobooks_generated":   audiobooks,
                "listening_hours_total":  round(total_secs / 3600, 1),
                "avg_completion_pct":     round(avg_compl, 1),
                "avg_session_minutes":    round(avg_sess_s / 60, 1),
            },
            "conversion": {
                "quota_exceeded_events_30d":   quota_exceeded,
                "paywall_views_30d":           paywall_views,
                "upgrade_clicks_30d":          upgrades,
                "upgrade_conversion_rate_pct": round(conv_rate, 1),
            },
        }

    @staticmethod
    async def get_growth(db: AsyncSession, days: int = 30) -> dict[str, Any]:
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        rows = (await db.execute(
            select(
                func.date(User.created_at).label("day"),
                func.count(User.id).label("signups"),
            )
            .where(User.created_at >= cutoff)
            .group_by(func.date(User.created_at))
            .order_by(func.date(User.created_at))
        )).all()

        return {
            "period_days": days,
            "data": [{"day": str(r.day), "signups": r.signups} for r in rows],
        }

    @staticmethod
    async def get_activity(db: AsyncSession, limit: int = 50) -> dict[str, Any]:
        rows = (await db.execute(
            select(
                AnalyticsEvent.event_type,
                AnalyticsEvent.created_at,
                AnalyticsEvent.user_id,
                AnalyticsEvent.properties,
            )
            .order_by(AnalyticsEvent.created_at.desc())
            .limit(limit)
        )).all()

        events = [
            {
                "event_type":     row.event_type,
                "label":          _ACTIVITY_LABELS.get(row.event_type, row.event_type.replace("_", " ").title()),
                "severity":       _activity_severity(row.event_type),
                "user_id_prefix": str(row.user_id)[:8] if row.user_id else "anon",
                "created_at":     row.created_at.isoformat() if row.created_at else None,
                "properties":     _strip_props(row.properties),
            }
            for row in rows
        ]
        return {"events": events, "total": len(events)}

"""
Analytics Service
=================
Records behavioral events and playback sessions; queries aggregates for
admin visibility.

All write methods catch DB errors and log warnings rather than raising —
analytics must never break the user experience.

All query methods return plain dicts so routers can JSON-serialise them
without an ORM-to-Pydantic step.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any, Optional
from uuid import UUID, uuid4

from sqlalchemy import and_, case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.analytics import AnalyticsEvent, PlaybackSession

logger = logging.getLogger(__name__)

# Sensitive property keys stripped before persisting to DB
_BLOCKED_PROPS = frozenset({"password", "token", "secret", "card", "ssn", "cvv"})


def _sanitise(props: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in props.items() if k.lower() not in _BLOCKED_PROPS}


class AnalyticsService:
    """
    Stateless service — all methods are static and accept db as first arg.
    Follows the same convention as CostTracker.
    """

    # ── Writes ────────────────────────────────────────────────────────────────

    @staticmethod
    async def record_event(
        db: AsyncSession,
        user_id: Optional[UUID],
        event_type: str,
        properties: Optional[dict[str, Any]] = None,
        document_id: Optional[UUID] = None,
        session_id: Optional[UUID] = None,
    ) -> None:
        """
        Persist an analytics event.  Silently swallows DB errors so a broken
        analytics write never surfaces as a 500 to the user.
        """
        try:
            event = AnalyticsEvent(
                user_id=user_id,
                event_type=event_type,
                properties=_sanitise(properties or {}),
                document_id=document_id,
                session_id=session_id,
            )
            db.add(event)
            await db.commit()
            logger.info(
                "[SONORO] analytics_event_recorded event_type=%s user_id=%s",
                event_type, user_id,
            )
        except Exception as exc:
            logger.warning(
                "[SONORO] analytics_event_write_failed event_type=%s error=%s",
                event_type, exc,
            )
            await db.rollback()

    @staticmethod
    async def start_session(
        db: AsyncSession,
        user_id: UUID,
        document_id: Optional[UUID],
        source: str = "direct",
        resumed_from_continue_listening: bool = False,
    ) -> Optional[str]:
        """
        Create a PlaybackSession row.  Returns the session UUID string, or
        None if the DB write fails (analytics degraded gracefully).
        """
        try:
            session = PlaybackSession(
                user_id=user_id,
                document_id=document_id,
                session_source=source,
                resumed_from_continue_listening=resumed_from_continue_listening,
            )
            db.add(session)
            await db.commit()
            await db.refresh(session)
            logger.info(
                "[SONORO] playback_session_started session_id=%s user_id=%s doc_id=%s source=%s",
                session.id, user_id, document_id, source,
            )
            return str(session.id)
        except Exception as exc:
            logger.warning(
                "[SONORO] playback_session_start_failed user_id=%s error=%s", user_id, exc
            )
            await db.rollback()
            return None

    @staticmethod
    async def end_session(
        db: AsyncSession,
        session_id: UUID,
        listened_seconds: int,
        completion_percentage: float,
        playback_speed: float = 1.0,
        chapters_visited: Optional[list[int]] = None,
    ) -> None:
        """
        Mark a PlaybackSession as ended with final listening metrics.
        """
        try:
            result = await db.execute(
                select(PlaybackSession).where(PlaybackSession.id == session_id)
            )
            session = result.scalar_one_or_none()
            if not session:
                logger.warning(
                    "[SONORO] playback_session_not_found session_id=%s", session_id
                )
                return

            session.ended_at             = datetime.utcnow()
            session.listened_seconds     = max(0, listened_seconds)
            session.completion_percentage = min(100.0, max(0.0, completion_percentage))
            session.playback_speed       = playback_speed
            session.chapters_visited     = chapters_visited or []

            await db.commit()

            logger.info(
                "[SONORO] playback_session_completed session_id=%s listened_s=%d completion=%.1f%%",
                session_id, listened_seconds, completion_percentage,
            )
            if completion_percentage >= 90:
                logger.info(
                    "[SONORO] audiobook_completed session_id=%s user_id=%s doc_id=%s",
                    session_id, session.user_id, session.document_id,
                )
        except Exception as exc:
            logger.warning(
                "[SONORO] playback_session_end_failed session_id=%s error=%s", session_id, exc
            )
            await db.rollback()

    # ── Queries ───────────────────────────────────────────────────────────────

    @staticmethod
    async def get_completion_stats(db: AsyncSession, days: int = 30) -> dict:
        """
        Listening completion rate buckets for the last *days* days.

        KPIs:
          engaged    — listened past 10%
          halfway    — listened past 50%
          completed  — listened past 90%
          avg_completion_pct — mean across all sessions
        """
        since = datetime.utcnow() - timedelta(days=days)

        result = await db.execute(
            select(
                func.count(PlaybackSession.id).label("total_sessions"),
                func.avg(PlaybackSession.completion_percentage).label("avg_completion_pct"),
                func.avg(PlaybackSession.listened_seconds).label("avg_listened_seconds"),
                func.count(case(
                    (PlaybackSession.completion_percentage >= 10, 1),
                )).label("engaged_count"),
                func.count(case(
                    (PlaybackSession.completion_percentage >= 50, 1),
                )).label("halfway_count"),
                func.count(case(
                    (PlaybackSession.completion_percentage >= 90, 1),
                )).label("completed_count"),
            )
            .where(PlaybackSession.started_at >= since)
        )
        row = result.one()

        total = row.total_sessions or 0

        def rate(n: int) -> float:
            return round(n / total * 100, 1) if total > 0 else 0.0

        return {
            "period_days":           days,
            "total_sessions":        total,
            "avg_completion_pct":    round(float(row.avg_completion_pct or 0), 1),
            "avg_listened_seconds":  round(float(row.avg_listened_seconds or 0)),
            "engaged_rate_pct":      rate(row.engaged_count or 0),
            "halfway_rate_pct":      rate(row.halfway_count or 0),
            "completed_rate_pct":    rate(row.completed_count or 0),
        }

    @staticmethod
    async def get_session_summary(db: AsyncSession, days: int = 30) -> dict:
        """Session-level aggregate: avg length, speed, CL resume rate."""
        since = datetime.utcnow() - timedelta(days=days)

        result = await db.execute(
            select(
                func.count(PlaybackSession.id).label("total_sessions"),
                func.count(func.distinct(PlaybackSession.user_id)).label("unique_users"),
                func.avg(PlaybackSession.listened_seconds).label("avg_duration_seconds"),
                func.avg(PlaybackSession.playback_speed).label("avg_speed"),
                func.count(case(
                    (PlaybackSession.resumed_from_continue_listening == True, 1),
                )).label("cl_resumes"),
            )
            .where(PlaybackSession.started_at >= since)
        )
        row = result.one()

        total = row.total_sessions or 0
        cl_rate = round((row.cl_resumes or 0) / total * 100, 1) if total > 0 else 0.0

        return {
            "period_days":              days,
            "total_sessions":           total,
            "unique_users":             row.unique_users or 0,
            "avg_duration_seconds":     round(float(row.avg_duration_seconds or 0)),
            "avg_playback_speed":       round(float(row.avg_speed or 1.0), 2),
            "continue_listening_rate_pct": cl_rate,
        }

    @staticmethod
    async def get_top_events(db: AsyncSession, days: int = 30) -> list[dict]:
        """Most common event types in the last *days* days, ordered by count."""
        since = datetime.utcnow() - timedelta(days=days)

        result = await db.execute(
            select(
                AnalyticsEvent.event_type,
                func.count(AnalyticsEvent.id).label("count"),
            )
            .where(AnalyticsEvent.created_at >= since)
            .group_by(AnalyticsEvent.event_type)
            .order_by(func.count(AnalyticsEvent.id).desc())
            .limit(20)
        )

        return [
            {"event_type": row.event_type, "count": row.count}
            for row in result
        ]

    @staticmethod
    async def get_upgrade_triggers(db: AsyncSession, days: int = 90) -> dict:
        """
        Count paywall_viewed and upgrade_clicked events by source trigger.

        The frontend embeds a `trigger` key in properties when firing these
        events (e.g. "quota_exceeded", "audiobook_too_large").
        """
        since = datetime.utcnow() - timedelta(days=days)

        paywall_result = await db.execute(
            select(func.count(AnalyticsEvent.id))
            .where(and_(
                AnalyticsEvent.event_type == "paywall_viewed",
                AnalyticsEvent.created_at >= since,
            ))
        )
        upgrade_result = await db.execute(
            select(func.count(AnalyticsEvent.id))
            .where(and_(
                AnalyticsEvent.event_type == "upgrade_clicked",
                AnalyticsEvent.created_at >= since,
            ))
        )
        complete_result = await db.execute(
            select(func.count(AnalyticsEvent.id))
            .where(and_(
                AnalyticsEvent.event_type.in_(["upgrade_complete", "checkout_completed"]),
                AnalyticsEvent.created_at >= since,
            ))
        )

        paywall_count = paywall_result.scalar() or 0
        upgrade_count = upgrade_result.scalar() or 0
        complete_count = complete_result.scalar() or 0

        click_rate = round(upgrade_count / paywall_count * 100, 1) if paywall_count else 0.0
        convert_rate = round(complete_count / upgrade_count * 100, 1) if upgrade_count else 0.0

        logger.info(
            "[SONORO] upgrade_trigger_detected paywall=%d clicked=%d converted=%d",
            paywall_count, upgrade_count, complete_count,
        )

        return {
            "period_days":         days,
            "paywall_views":       paywall_count,
            "upgrade_clicks":      upgrade_count,
            "conversions":         complete_count,
            "paywall_click_rate":  click_rate,
            "click_convert_rate":  convert_rate,
        }

    @staticmethod
    async def get_retention_signals(db: AsyncSession) -> dict:
        """
        Multi-session retention: how many users came back?

        Returns:
          total_users_with_sessions — unique users who have any session
          returning_users           — users with > 1 session (day-1+)
          retention_rate_pct        — returning / total
          avg_sessions_per_user     — mean sessions per user
        """
        subq = (
            select(
                PlaybackSession.user_id,
                func.count(PlaybackSession.id).label("session_count"),
            )
            .group_by(PlaybackSession.user_id)
            .subquery()
        )

        result = await db.execute(
            select(
                func.count(subq.c.user_id).label("total_users"),
                func.count(case(
                    (subq.c.session_count > 1, 1),
                )).label("returning_users"),
                func.avg(subq.c.session_count).label("avg_sessions"),
            )
        )
        row = result.one()

        total = row.total_users or 0
        returning = row.returning_users or 0
        retention_rate = round(returning / total * 100, 1) if total > 0 else 0.0

        logger.info(
            "[SONORO] retention_signal_detected total_users=%d returning=%d retention_pct=%.1f",
            total, returning, retention_rate,
        )

        return {
            "total_users_with_sessions": total,
            "returning_users":           returning,
            "retention_rate_pct":        retention_rate,
            "avg_sessions_per_user":     round(float(row.avg_sessions or 0), 2),
        }

    @staticmethod
    async def get_voice_engagement(db: AsyncSession, days: int = 30) -> list[dict]:
        """
        Most-previewed voices from voice_preview_played events.

        The frontend embeds voice_id in event properties when firing the event.
        Uses PostgreSQL JSON operator to extract the field.
        """
        since = datetime.utcnow() - timedelta(days=days)

        result = await db.execute(
            select(
                AnalyticsEvent.properties["voice_id"].as_string().label("voice_id"),
                func.count(AnalyticsEvent.id).label("preview_count"),
            )
            .where(and_(
                AnalyticsEvent.event_type == "voice_preview_played",
                AnalyticsEvent.created_at >= since,
            ))
            .group_by(AnalyticsEvent.properties["voice_id"].as_string())
            .order_by(func.count(AnalyticsEvent.id).desc())
            .limit(10)
        )

        voices = [
            {"voice_id": row.voice_id, "preview_count": row.preview_count}
            for row in result
            if row.voice_id
        ]

        if voices:
            logger.info(
                "[SONORO] voice_engagement_recorded top_voice=%s count=%d",
                voices[0]["voice_id"], voices[0]["preview_count"],
            )

        return voices

"""
Quota Service
=============
Service for checking and enforcing monthly usage quotas.

All database queries use SQLAlchemy 2.0 Core-style select() statements
(not the legacy db.query() API, which does not exist on AsyncSession).
"""

from datetime import datetime, timedelta
from typing import Dict  # noqa: UP006 — consistent with rest of codebase
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import get_logger
from app.db.models import User
from app.financial.cost.cost_models import UsageQuota
from app.financial.cost.cost_enums import ActionType
from app.financial.quota.quota_limits import PlanTier, get_plan_limits

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class QuotaExceeded(HTTPException):
    """Raised in API context (HTTP 429) when a quota limit is breached."""

    def __init__(self, message: str, quota_type: str):
        super().__init__(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "error": "quota_exceeded",
                "message": message,
                "quota_type": quota_type,
            },
        )


class QuotaExhaustedError(Exception):
    """
    Raised in worker context (non-HTTP) when character quota is exhausted.

    This exception is intentionally separate from QuotaExceeded so that the
    Celery task can catch it specifically and avoid triggering a retry — a
    quota failure is permanent until the next billing period, not transient.
    """


# ---------------------------------------------------------------------------
# QuotaService
# ---------------------------------------------------------------------------


class QuotaService:
    """
    Manage user quotas and usage limits.

    All methods are staticmethods so they can be called without instantiation,
    consistent with how CostTracker is used.
    """

    @staticmethod
    async def get_or_create_quota(
        db: AsyncSession,
        user_id: UUID,
    ) -> UsageQuota:
        """
        Return the current-period UsageQuota for user, creating or resetting it
        if it doesn't exist or the period has expired.
        """
        result = await db.execute(
            select(UsageQuota).where(UsageQuota.user_id == user_id)
        )
        quota = result.scalar_one_or_none()

        if quota:
            if datetime.utcnow() >= quota.period_end:
                # New billing period — reset counters (storage persists)
                quota.period_start = datetime.utcnow()
                quota.period_end = quota.period_start + timedelta(days=30)
                quota.characters_used = 0
                quota.jobs_created = 0
                quota.api_calls = 0
                await db.commit()
                await db.refresh(quota)
                logger.info("[SONORO] quota_period_reset", user_id=str(user_id))
        else:
            now = datetime.utcnow()
            quota = UsageQuota(
                user_id=user_id,
                period_start=now,
                period_end=now + timedelta(days=30),
            )
            db.add(quota)
            await db.commit()
            await db.refresh(quota)
            logger.info("[SONORO] quota_created", user_id=str(user_id))

        return quota

    @staticmethod
    async def check_quota(
        db: AsyncSession,
        user_id: UUID,
        action_type: ActionType,
        amount: int = 1,
    ) -> bool:
        """
        Check whether the user has quota remaining for *action_type*.

        Intended for API-layer callers.

        Raises:
            QuotaExceeded (HTTP 429): If the limit would be exceeded.
        """
        user = await db.get(User, user_id)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        plan_tier = PlanTier(user.plan_tier) if user.plan_tier else PlanTier.FREE
        limits = get_plan_limits(plan_tier)
        quota = await QuotaService.get_or_create_quota(db, user_id)

        if action_type == ActionType.TTS_CHARACTER_USE:
            if quota.characters_used + amount > limits.monthly_char_limit:
                logger.warning(
                    "[SONORO] quota_exceeded",
                    user_id=str(user_id),
                    used=quota.characters_used,
                    limit=limits.monthly_char_limit,
                    requested=amount,
                )
                raise QuotaExceeded(
                    f"Monthly character limit exceeded. "
                    f"Used: {quota.characters_used:,}, "
                    f"Limit: {limits.monthly_char_limit:,}",
                    "monthly_characters",
                )

        elif action_type == ActionType.TTS_JOB_CREATE:
            if quota.jobs_created + amount > limits.monthly_job_limit:
                raise QuotaExceeded(
                    f"Monthly job limit exceeded. "
                    f"Used: {quota.jobs_created}, "
                    f"Limit: {limits.monthly_job_limit}",
                    "monthly_jobs",
                )

        elif action_type == ActionType.STORAGE_USE:
            if quota.storage_used_mb + amount > limits.storage_limit_mb:
                raise QuotaExceeded(
                    f"Storage limit exceeded. "
                    f"Used: {quota.storage_used_mb:.1f} MB, "
                    f"Limit: {limits.storage_limit_mb} MB",
                    "storage",
                )

        logger.info(
            "[SONORO] quota_checked",
            user_id=str(user_id),
            action=action_type.value,
            used=quota.characters_used if action_type == ActionType.TTS_CHARACTER_USE else quota.jobs_created,
            limit=limits.monthly_char_limit if action_type == ActionType.TTS_CHARACTER_USE else limits.monthly_job_limit,
            requested=amount,
        )
        return True

    @staticmethod
    async def check_character_quota_for_worker(
        db: AsyncSession,
        user_id: UUID,
        requested_chars: int,
    ) -> None:
        """
        Quota check for Celery worker context.

        Unlike check_quota(), this raises QuotaExhaustedError (not HTTPException)
        so the task can fail permanently without triggering a retry.
        """
        user = await db.get(User, user_id)
        plan_tier = PlanTier(user.plan_tier if user and user.plan_tier else "FREE")
        limits = get_plan_limits(plan_tier)

        quota = await QuotaService.get_or_create_quota(db, user_id)
        used = quota.characters_used

        logger.info(
            "[SONORO] quota_checked",
            user_id=str(user_id),
            used=used,
            limit=limits.monthly_char_limit,
            requested=requested_chars,
        )

        if used + requested_chars > limits.monthly_char_limit:
            logger.warning(
                "[SONORO] quota_exceeded",
                user_id=str(user_id),
                used=used,
                limit=limits.monthly_char_limit,
                requested=requested_chars,
            )
            raise QuotaExhaustedError(
                f"Monthly character quota exceeded: "
                f"used={used:,}, requested={requested_chars:,}, "
                f"limit={limits.monthly_char_limit:,}. "
                f"Upgrade your plan or wait for the next billing period."
            )

    @staticmethod
    async def increment_usage(
        db: AsyncSession,
        user_id: UUID,
        action_type: ActionType,
        amount: int = 1,
    ) -> UsageQuota:
        """Increment a usage counter and persist."""
        quota = await QuotaService.get_or_create_quota(db, user_id)

        if action_type == ActionType.TTS_CHARACTER_USE:
            quota.characters_used += amount
        elif action_type == ActionType.TTS_JOB_CREATE:
            quota.jobs_created += amount
        elif action_type == ActionType.STORAGE_USE:
            quota.storage_used_mb += amount
        elif action_type == ActionType.API_CALL:
            quota.api_calls += amount

        await db.commit()
        await db.refresh(quota)

        logger.debug(
            "[SONORO] quota_incremented",
            user_id=str(user_id),
            action=action_type.value,
            amount=amount,
            chars_used=quota.characters_used,
            jobs_created=quota.jobs_created,
        )
        return quota

    @staticmethod
    async def get_remaining_quota(
        db: AsyncSession,
        user_id: UUID,
    ) -> Dict:
        """Return remaining quota for all dimensions."""
        user = await db.get(User, user_id)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        plan_tier = PlanTier(user.plan_tier) if user.plan_tier else PlanTier.FREE
        limits = get_plan_limits(plan_tier)
        quota = await QuotaService.get_or_create_quota(db, user_id)

        return {
            "plan_tier": plan_tier.value,
            "period_start": quota.period_start.isoformat(),
            "period_end": quota.period_end.isoformat(),
            "characters": {
                "used": quota.characters_used,
                "limit": limits.monthly_char_limit,
                "remaining": max(0, limits.monthly_char_limit - quota.characters_used),
                "percentage": (
                    quota.characters_used / limits.monthly_char_limit * 100
                    if limits.monthly_char_limit > 0
                    else 0
                ),
            },
            "jobs": {
                "used": quota.jobs_created,
                "limit": limits.monthly_job_limit,
                "remaining": max(0, limits.monthly_job_limit - quota.jobs_created),
                "percentage": (
                    quota.jobs_created / limits.monthly_job_limit * 100
                    if limits.monthly_job_limit > 0
                    else 0
                ),
            },
            "storage": {
                "used_mb": quota.storage_used_mb,
                "limit_mb": limits.storage_limit_mb,
                "remaining_mb": max(0, limits.storage_limit_mb - quota.storage_used_mb),
                "percentage": (
                    quota.storage_used_mb / limits.storage_limit_mb * 100
                    if limits.storage_limit_mb > 0
                    else 0
                ),
            },
            "api_calls": {
                "used": quota.api_calls,
                "limit_per_day": limits.api_calls_per_day,
            },
        }

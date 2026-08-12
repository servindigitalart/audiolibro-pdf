"""
Cost Guard — pre-generation spend protection
============================================
The single gate every expensive TTS run must pass through.

This is NOT a second protection system.  Per-user rules live in
`RevenueProtectionService` and are delegated to unchanged; this module supplies
the accumulated-spend numbers that service has always required as inputs, and
adds the two rules that are not per-user: a per-job ceiling and a global cap.

Enforcement is layered on purpose:

  ALWAYS ON — cannot be disabled by a feature flag
    1. Emergency shutdown  (settings.emergency_shutdown_mode)
    2. Global month-to-date cap (settings.global_monthly_cost_cap)
    3. Per-job estimate ceiling (settings.max_job_cost_usd)

  FLAG-GATED — settings.hard_cost_limit_enabled, default False
    4. Per-user daily / monthly tier caps + negative-margin throttle

Why the split: TIER_CATALOG's daily caps are calibrated for usage smoothed
across a month, not for single-job spend.  FREE allows 50,000 chars/month but
caps daily cost at $0.09, while 50,000 chars of Neural2 audio costs $0.80.
Enforcing the daily cap against a job estimate would reject every FREE user's
first real conversion.  The always-on layer is calibrated so it never trips a
legitimate book ($25 ceiling vs. ~$8.64 for a 540k-char worst case), so it can
be safe by default; the tier caps stay off until they are recalibrated.

Failing safe: any *expected* rejection raises CostProtectionError and the job
is marked FAILED without retry.  Redis being unreachable degrades to the DB
checks rather than opening the gate — see `check_processing_allowed`.
"""
from __future__ import annotations

import logging
from typing import Any, Optional
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.financial.cost.cost_tracker import CostTracker
from app.financial.financial_metrics import (
    cost_cap_exceeded_total,
    emergency_shutdown_triggered,
)
from app.pricing.protection import (
    CostCapExceeded,
    NegativeMarginThrottle,
    RevenueProtectionService,
)
from app.pricing.tiers import PlanTier

logger = logging.getLogger(__name__)


class CostProtectionError(Exception):
    """
    Raised when a job is not permitted to spend.

    Carries a user-facing message (`user_message`) separate from the log text,
    and a machine-readable `reason` for metrics and analytics.
    """

    def __init__(self, reason: str, user_message: str) -> None:
        super().__init__(f"[{reason}] {user_message}")
        self.reason = reason
        self.user_message = user_message


async def check_processing_allowed(
    db: AsyncSession,
    user_id: UUID,
    plan_tier: str,
    estimated_job_cost_usd: float,
    redis: Optional[Any] = None,
) -> None:
    """
    Decide whether this job may start expensive TTS work.

    Returns None when permitted.  Raises CostProtectionError when not — call
    this BEFORE the first provider request, never after.
    """
    user_ref = str(user_id)

    # ── 1. Emergency shutdown ────────────────────────────────────────────────
    if settings.emergency_shutdown_mode:
        emergency_shutdown_triggered.labels(reason="processing_blocked").inc()
        logger.error(
            "[SONORO] cost_protection_rejected reason=emergency_shutdown "
            "user_id=%s estimated_cost_usd=%.4f",
            user_ref, estimated_job_cost_usd,
        )
        raise CostProtectionError(
            "emergency_shutdown",
            "Processing is temporarily paused for maintenance. "
            "Your document is safe — please retry shortly.",
        )

    # ── 2. Per-job ceiling ───────────────────────────────────────────────────
    # Always on: calibrated well above any legitimate book, so it only catches
    # pathological documents.
    try:
        RevenueProtectionService.check_job_estimate(
            user_ref, estimated_job_cost_usd, settings.max_job_cost_usd
        )
    except CostCapExceeded as e:
        cost_cap_exceeded_total.labels(cap_type="job").inc()
        logger.error(
            "[SONORO] cost_protection_rejected reason=job_cost_ceiling "
            "user_id=%s estimated_cost_usd=%.4f cap_usd=%.4f",
            user_ref, e.cost, e.cap,
        )
        raise CostProtectionError(
            "job_cost_ceiling",
            f"This document is too large to convert in one job "
            f"(estimated provider cost ${e.cost:.2f}, limit ${e.cap:.2f}). "
            f"Please split it into smaller documents.",
        ) from e

    # ── 3. Global month-to-date cap ──────────────────────────────────────────
    system_mtd = await CostTracker.get_system_month_to_date_cost(db)
    global_cap = settings.global_monthly_cost_cap
    if global_cap > 0 and system_mtd + estimated_job_cost_usd > global_cap:
        cost_cap_exceeded_total.labels(cap_type="global_monthly").inc()
        logger.error(
            "[SONORO] cost_protection_rejected reason=global_monthly_cap "
            "user_id=%s system_mtd_usd=%.4f estimated_cost_usd=%.4f cap_usd=%.4f",
            user_ref, system_mtd, estimated_job_cost_usd, global_cap,
        )
        raise CostProtectionError(
            "global_monthly_cap",
            "Processing is temporarily paused while we review capacity. "
            "Your document is safe — please retry later.",
        )

    # ── 4. Per-user tier caps (flag-gated) ───────────────────────────────────
    if not settings.hard_cost_limit_enabled:
        logger.info(
            "[SONORO] cost_protection_check user_id=%s estimated_cost_usd=%.4f "
            "system_mtd_usd=%.4f user_caps=disabled result=allowed",
            user_ref, estimated_job_cost_usd, system_mtd,
        )
        return

    if redis is None:
        # The throttle flag lives in Redis.  Without it we can still enforce the
        # DB-derived daily/monthly caps, which are the ones that bound spend.
        logger.warning(
            "[SONORO] cost_protection_degraded user_id=%s reason=no_redis "
            "— enforcing DB caps only",
            user_ref,
        )

    daily = await CostTracker.get_user_daily_cost(db, user_id)
    monthly = (await CostTracker.get_user_monthly_cost(db, user_id))["total_cost"]

    try:
        if redis is not None:
            await RevenueProtectionService(redis).check(user_ref, plan_tier, daily, monthly)
        else:
            _check_caps_without_redis(user_ref, plan_tier, daily, monthly)
    except CostCapExceeded as e:
        cost_cap_exceeded_total.labels(cap_type=e.cap_type).inc()
        logger.error(
            "[SONORO] cost_protection_rejected reason=user_%s_cap user_id=%s "
            "spend_usd=%.4f cap_usd=%.4f",
            e.cap_type, user_ref, e.cost, e.cap,
        )
        raise CostProtectionError(
            f"user_{e.cap_type}_cap",
            f"You have reached your plan's {e.cap_type} processing limit. "
            f"Upgrade your plan or try again later.",
        ) from e
    except NegativeMarginThrottle as e:
        cost_cap_exceeded_total.labels(cap_type="throttle").inc()
        logger.error(
            "[SONORO] cost_protection_rejected reason=throttle user_id=%s", user_ref,
        )
        raise CostProtectionError(
            "throttle",
            "Your account is temporarily rate-limited for unusually high usage. "
            "Please try again later.",
        ) from e

    logger.info(
        "[SONORO] cost_protection_check user_id=%s estimated_cost_usd=%.4f "
        "daily_usd=%.4f monthly_usd=%.4f result=allowed",
        user_ref, estimated_job_cost_usd, daily, monthly,
    )


def _check_caps_without_redis(
    user_ref: str,
    plan_tier: str,
    daily_cost_usd: float,
    monthly_cost_usd: float,
) -> None:
    """Daily + monthly tier caps, minus the Redis-backed throttle rules."""
    from app.pricing.tiers import TIER_CATALOG

    try:
        tier = PlanTier(str(plan_tier).upper())
    except ValueError:
        tier = PlanTier.FREE
    config = TIER_CATALOG[tier]

    if daily_cost_usd >= config.max_daily_cost_usd:
        raise CostCapExceeded(user_ref, "daily", daily_cost_usd, config.max_daily_cost_usd)
    if monthly_cost_usd >= config.max_monthly_cost_usd:
        raise CostCapExceeded(user_ref, "monthly", monthly_cost_usd, config.max_monthly_cost_usd)

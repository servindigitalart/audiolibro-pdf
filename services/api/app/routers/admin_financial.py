"""
Admin Financial Router
=====================
Admin-only endpoints for cost monitoring and quota management.
"""

import calendar
from datetime import datetime
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth_dependencies import require_admin
from app.core.logging_config import get_logger
from app.db.models.user import User
from app.db.session import get_db
from app.financial.cost.cost_tracker import CostTracker
from app.financial.quota.quota_service import QuotaService

logger = get_logger(__name__)

router = APIRouter(prefix="/api/v1/admin/financial", tags=["admin", "financial"])


@router.get("/cost/overview")
async def get_cost_overview(
    days: int = Query(default=30, ge=1, le=365, description="Number of days to analyze"),
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """
    Get system-wide cost overview.
    
    **Admin only**
    
    Returns:
    - Total monthly cost
    - Cost breakdown by type and provider
    - Daily cost trend
    - Top spending users
    """
    # CostTracker is an all-@staticmethod namespace; it takes no constructor.
    monthly_cost = await CostTracker.get_system_monthly_cost(db)
    trend = await CostTracker.get_system_cost_trend(db, days=days)
    failures = await CostTracker.get_failure_cost_summary(db, days=days)
    by_voice = await CostTracker.get_cost_by_voice(db, days=days)
    top_users = await CostTracker.get_top_spending_users(db, days=days)

    # Straight-line projection from month-to-date spend.  Crude on purpose —
    # one honest number beats a forecast model nobody can audit.
    now = datetime.utcnow()
    days_elapsed = max(1, now.day)
    days_in_month = calendar.monthrange(now.year, now.month)[1]
    mtd = float(monthly_cost.get("total_cost") or 0.0)

    logger.info(
        "admin_cost_overview_accessed",
        admin_id=str(current_user.id),
        admin_email=current_user.email,
        days=days,
    )

    return {
        "period": "current_month",
        "days_analyzed": days,
        "monthly_summary": monthly_cost,
        "daily_trend": trend,
        "failure_summary": failures,
        "cost_by_voice": by_voice,
        "top_spending_users": top_users,
        "month_to_date_usd": round(mtd, 6),
        "projected_month_end_usd": round(mtd / days_elapsed * days_in_month, 6),
        "cost_basis": (
            "Calculated from published provider per-character rates. "
            "Not an invoice amount — the provider exposes no per-request charge."
        ),
        "accessed_by": current_user.email,
        "accessed_at": datetime.utcnow().isoformat(),
    }


@router.get("/cost/user/{user_id}")
async def get_user_cost(
    user_id: UUID,
    days: int = Query(default=30, ge=1, le=365, description="Number of days to analyze"),
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """
    Get detailed cost information for a specific user.
    
    **Admin only**
    
    Returns:
    - Monthly cost with breakdown
    - Daily cost trend
    - Event count by type
    """
    monthly_cost = await CostTracker.get_user_monthly_cost(db, user_id)
    trend = await CostTracker.get_user_cost_trend(db, user_id, days=days)
    daily_cost = await CostTracker.get_user_daily_cost(db, user_id)

    logger.info(
        "admin_user_cost_accessed",
        admin_id=str(current_user.id),
        admin_email=current_user.email,
        target_user_id=str(user_id),
        days=days,
    )
    
    return {
        "user_id": str(user_id),
        "period": "current_month",
        "days_analyzed": days,
        "monthly_summary": monthly_cost,
        "daily_cost_usd": round(daily_cost, 6),
        "daily_trend": trend,
        "accessed_by": current_user.email,
        "accessed_at": datetime.utcnow().isoformat(),
    }


@router.get("/quota/{user_id}")
async def get_user_quota(
    user_id: UUID,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """
    Get quota information for a specific user.
    
    **Admin only**
    
    Returns:
    - Current usage
    - Remaining quota
    - Usage percentages
    - Period information
    """
    quota_service = QuotaService(db)
    
    # Get user to check plan tier
    from sqlalchemy import select
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    # Get or create quota
    quota = await quota_service.get_or_create_quota(user_id, user.plan_tier)
    
    # Get remaining quota for all action types
    from app.financial.cost.cost_enums import ActionType
    remaining = {}
    
    for action in ActionType:
        try:
            remaining[action] = await quota_service.get_remaining_quota(
                user_id, user.plan_tier, action
            )
        except Exception as e:
            logger.error(
                "error_getting_remaining_quota",
                user_id=str(user_id),
                action=action,
                error=str(e),
            )
            remaining[action] = None
    
    logger.info(
        "admin_user_quota_accessed",
        admin_id=str(current_user.id),
        admin_email=current_user.email,
        target_user_id=str(user_id),
    )
    
    return {
        "user_id": str(user_id),
        "plan_tier": user.plan_tier,
        "current_usage": {
            "characters_used": quota.characters_used,
            "jobs_created": quota.jobs_created,
            "storage_used_mb": quota.storage_used_mb,
            "api_calls": quota.api_calls,
        },
        "remaining_quota": remaining,
        "period": {
            "start": quota.period_start.isoformat(),
            "end": quota.period_end.isoformat(),
        },
        "accessed_by": current_user.email,
        "accessed_at": datetime.utcnow().isoformat(),
    }


@router.post("/quota/{user_id}/reset")
async def reset_user_quota(
    user_id: UUID,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """
    Reset quota for a specific user (admin override).
    
    **Admin only**
    
    This creates a new quota period starting now.
    """
    quota_service = QuotaService(db)
    
    # Get user
    from sqlalchemy import select
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    # Get current quota
    quota = await quota_service.get_or_create_quota(user_id, user.plan_tier)
    
    # Reset usage
    quota.characters_used = 0
    quota.jobs_created = 0
    quota.storage_used_mb = 0
    quota.api_calls = 0
    
    # Start new period
    from datetime import timedelta
    quota.period_start = datetime.utcnow()
    quota.period_end = quota.period_start + timedelta(days=30)
    
    await db.commit()
    await db.refresh(quota)
    
    logger.warning(
        "admin_quota_reset",
        admin_id=str(current_user.id),
        admin_email=current_user.email,
        target_user_id=str(user_id),
        reason="admin_override",
    )
    
    return {
        "user_id": str(user_id),
        "status": "reset",
        "new_period_start": quota.period_start.isoformat(),
        "new_period_end": quota.period_end.isoformat(),
        "reset_by": current_user.email,
        "reset_at": datetime.utcnow().isoformat(),
    }


@router.get("/plan-economics")
async def get_plan_economics(
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """
    Real per-plan average cost from completed jobs with cost telemetry.

    **Admin only**

    Requires migration 021 (plan_tier_at_generation column).  Returns empty
    list until at least one job has completed after the migration is applied.

    Returns per-tier: job_count, avg_cost_usd, total_cost_usd, avg_chars.
    Also appends theoretical unit economics from UnitEconomicsEngine for
    comparison against observed averages.
    """
    from app.pricing.unit_economics import UnitEconomicsEngine
    from app.pricing.tiers import PlanTier

    observed = await CostTracker.get_plan_economics(db)

    engine = UnitEconomicsEngine()
    theoretical = {
        tier.value: {
            "cost_per_listening_hour_usd": round(engine.cost_per_listening_hour(tier), 4),
            "break_even_utilization": round(
                engine.tier_economics(tier).break_even_utilization, 4
            ),
            "gross_margin_pct_at_60pct": round(
                engine.tier_economics(tier, 0.60).gross_margin_pct, 1
            ),
        }
        for tier in PlanTier
    }

    logger.info(
        "admin_plan_economics_accessed",
        admin_id=str(current_user.id),
        admin_email=current_user.email,
        observed_tier_count=len(observed),
    )

    return {
        "observed": observed,
        "theoretical": theoretical,
        "accessed_by": current_user.email,
        "accessed_at": datetime.utcnow().isoformat(),
    }


@router.get("/expensive-jobs")
async def get_expensive_jobs(
    limit: int = Query(default=20, ge=1, le=100, description="Number of jobs to return"),
    days: int = Query(default=30, ge=1, le=365, description="Lookback window in days"),
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """
    Top N most expensive completed jobs in the lookback window.

    **Admin only**

    Ordered by estimated_cost_usd descending.  Useful for identifying
    outlier users and runaway processing before they impact margins.
    """
    jobs = await CostTracker.get_expensive_jobs(db, limit=limit, days=days)

    logger.info(
        "admin_expensive_jobs_accessed",
        admin_id=str(current_user.id),
        admin_email=current_user.email,
        limit=limit,
        days=days,
        result_count=len(jobs),
    )

    return {
        "jobs": jobs,
        "limit": limit,
        "days": days,
        "accessed_by": current_user.email,
        "accessed_at": datetime.utcnow().isoformat(),
    }


@router.get("/cost/alert-status")
async def get_cost_alert_status(
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """
    Get cost cap alert status.
    
    **Admin only**
    
    Returns:
    - Current monthly cost
    - Cost cap settings
    - Alert threshold status
    - Whether emergency shutdown is active
    """
    from app.core.config import settings

    # get_system_monthly_cost returns the key "total_cost", not "total_cost_usd".
    total_cost = await CostTracker.get_system_month_to_date_cost(db)
    cost_cap = settings.global_monthly_cost_cap
    alert_threshold = settings.cost_alert_threshold_percentage
    
    threshold_reached = (total_cost / cost_cap * 100) if cost_cap > 0 else 0
    is_at_alert_threshold = threshold_reached >= alert_threshold
    is_at_cap = total_cost >= cost_cap
    
    logger.info(
        "admin_cost_alert_status_checked",
        admin_id=str(current_user.id),
        admin_email=current_user.email,
        total_cost=total_cost,
        threshold_percentage=threshold_reached,
    )
    
    return {
        "current_cost_usd": total_cost,
        "cost_cap_usd": cost_cap,
        "usage_percentage": round(threshold_reached, 2),
        "alert_threshold_percentage": alert_threshold,
        "is_at_alert_threshold": is_at_alert_threshold,
        "is_at_cap": is_at_cap,
        # Per-job ceiling — always enforced, unlike hard_cost_limit_enabled
        # below, which gates only the per-user tier caps.
        "max_job_cost_usd": settings.max_job_cost_usd,
        "emergency_shutdown_active": settings.emergency_shutdown_mode,
        "hard_cost_limit_enabled": settings.hard_cost_limit_enabled,
        "checked_by": current_user.email,
        "checked_at": datetime.utcnow().isoformat(),
    }

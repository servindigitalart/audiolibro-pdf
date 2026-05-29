"""
Admin Dashboard Router
=======================
Aggregated KPI endpoints for the internal founder/operator dashboard.

All endpoints are admin-only.  They consume existing analytics, billing,
and cost telemetry — no new tables or schemas required.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.dashboard_service import DashboardService
from app.core.auth_dependencies import require_admin
from app.db.models.user import User
from app.db.session import get_async_db as get_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/admin/dashboard", tags=["admin", "dashboard"])


@router.get("/kpis")
async def get_dashboard_kpis(
    current_user: User    = Depends(require_admin),
    db: AsyncSession      = Depends(get_db),
):
    """
    Aggregated executive KPIs: user counts, MRR, costs, content, conversion.

    **Admin only** — single call for the top-level overview section.
    """
    data = await DashboardService.get_kpis(db)
    logger.info("admin_dashboard_kpis_accessed admin_id=%s", current_user.id)
    return data


@router.get("/growth")
async def get_user_growth(
    days: int             = Query(default=30, ge=7, le=90),
    current_user: User    = Depends(require_admin),
    db: AsyncSession      = Depends(get_db),
):
    """
    Daily user signups over the last N days.

    **Admin only** — powers the growth sparkline in the executive section.
    """
    data = await DashboardService.get_growth(db, days=days)
    logger.info("admin_dashboard_growth_accessed admin_id=%s days=%d", current_user.id, days)
    return data


@router.get("/activity")
async def get_activity_feed(
    limit: int            = Query(default=50, ge=10, le=200),
    current_user: User    = Depends(require_admin),
    db: AsyncSession      = Depends(get_db),
):
    """
    Recent analytics events as a formatted activity feed.

    **Admin only** — real-time founder activity stream.
    """
    data = await DashboardService.get_activity(db, limit=limit)
    logger.info("admin_dashboard_activity_accessed admin_id=%s limit=%d", current_user.id, limit)
    return data

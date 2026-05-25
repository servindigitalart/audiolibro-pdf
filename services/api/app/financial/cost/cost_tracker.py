"""
Cost Tracker Service
====================
Service for tracking and reporting cost events.

All queries use SQLAlchemy 2.0 Core-style select() — the legacy
db.query() API does not exist on AsyncSession.
"""

from datetime import datetime, timedelta
from typing import Dict, List, Optional
from uuid import UUID

from sqlalchemy import func, and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import get_logger
from app.financial.cost.cost_models import CostEvent
from app.financial.cost.cost_enums import CostEventType, CostProvider

logger = get_logger(__name__)


class CostTracker:
    """
    Track cost events and produce financial reports.

    CostEvent rows are the source of truth for spend; UsageQuota rows are
    the source of truth for the user-facing quota counter.  These are
    intentionally separate so reporting (cost_tracker) and enforcement
    (quota_service) remain decoupled.
    """

    @staticmethod
    async def track_event(
        db: AsyncSession,
        user_id: UUID,
        event_type: CostEventType,
        quantity: float = 1.0,
        unit_cost: float = 0.0,
        provider: Optional[CostProvider] = None,
        metadata: Optional[Dict] = None,
    ) -> CostEvent:
        """
        Persist a cost event row.

        This is the only write path — all other methods are read-only reports.
        """
        total_cost = quantity * unit_cost

        event = CostEvent(
            user_id=user_id,
            event_type=event_type,
            provider=provider or CostProvider.INTERNAL,
            quantity=quantity,
            unit_cost=unit_cost,
            total_cost=total_cost,
            activity_metadata=metadata or {},
        )

        db.add(event)
        await db.commit()
        await db.refresh(event)

        logger.info(
            "Cost event tracked: user=%s type=%s quantity=%s cost=$%.4f",
            user_id, event_type, quantity, total_cost,
        )
        return event

    @staticmethod
    async def get_user_monthly_cost(
        db: AsyncSession,
        user_id: UUID,
        month: Optional[datetime] = None,
    ) -> Dict:
        """Total cost for *user_id* in *month* (defaults to current month)."""
        if month is None:
            month = datetime.utcnow()

        month_start = month.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        if month.month == 12:
            month_end = month_start.replace(year=month.year + 1, month=1)
        else:
            month_end = month_start.replace(month=month.month + 1)

        where = and_(
            CostEvent.user_id == user_id,
            CostEvent.created_at >= month_start,
            CostEvent.created_at < month_end,
        )

        # Total cost
        total_result = await db.execute(
            select(func.sum(CostEvent.total_cost)).where(where)
        )
        total_cost = total_result.scalar() or 0.0

        # Breakdown by event type
        breakdown_result = await db.execute(
            select(
                CostEvent.event_type,
                func.sum(CostEvent.total_cost).label("cost"),
                func.count(CostEvent.id).label("count"),
            )
            .where(where)
            .group_by(CostEvent.event_type)
        )
        breakdown = {
            str(row.event_type): {"cost": float(row.cost), "count": row.count}
            for row in breakdown_result
        }

        return {
            "user_id": str(user_id),
            "month": month_start.isoformat(),
            "total_cost": total_cost,
            "breakdown": breakdown,
        }

    @staticmethod
    async def get_system_monthly_cost(
        db: AsyncSession,
        month: Optional[datetime] = None,
    ) -> Dict:
        """System-wide cost breakdown for *month*."""
        if month is None:
            month = datetime.utcnow()

        month_start = month.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        if month.month == 12:
            month_end = month_start.replace(year=month.year + 1, month=1)
        else:
            month_end = month_start.replace(month=month.month + 1)

        where = and_(
            CostEvent.created_at >= month_start,
            CostEvent.created_at < month_end,
        )

        total_result = await db.execute(
            select(func.sum(CostEvent.total_cost)).where(where)
        )
        total_cost = total_result.scalar() or 0.0

        breakdown_result = await db.execute(
            select(
                CostEvent.event_type,
                func.sum(CostEvent.total_cost).label("cost"),
                func.count(CostEvent.id).label("count"),
            )
            .where(where)
            .group_by(CostEvent.event_type)
        )
        breakdown = {
            str(row.event_type): {"cost": float(row.cost), "count": row.count}
            for row in breakdown_result
        }

        provider_result = await db.execute(
            select(
                CostEvent.provider,
                func.sum(CostEvent.total_cost).label("cost"),
            )
            .where(where)
            .group_by(CostEvent.provider)
        )
        by_provider = {str(row.provider): float(row.cost) for row in provider_result}

        return {
            "month": month_start.isoformat(),
            "total_cost": total_cost,
            "breakdown_by_type": breakdown,
            "breakdown_by_provider": by_provider,
        }

    @staticmethod
    async def get_user_cost_trend(
        db: AsyncSession,
        user_id: UUID,
        days: int = 30,
    ) -> List[Dict]:
        """Daily cost trend for *user_id* over the last *days* days."""
        start_date = datetime.utcnow() - timedelta(days=days)

        result = await db.execute(
            select(
                func.date_trunc("day", CostEvent.created_at).label("date"),
                func.sum(CostEvent.total_cost).label("cost"),
            )
            .where(
                and_(
                    CostEvent.user_id == user_id,
                    CostEvent.created_at >= start_date,
                )
            )
            .group_by(func.date_trunc("day", CostEvent.created_at))
            .order_by(func.date_trunc("day", CostEvent.created_at))
        )

        return [
            {"date": row.date.strftime("%Y-%m-%d"), "cost": float(row.cost)}
            for row in result
        ]

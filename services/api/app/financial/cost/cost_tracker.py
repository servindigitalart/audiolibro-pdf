"""
Cost Tracker Service
====================
Service for tracking and reporting cost events.
"""

from datetime import datetime, timedelta
from typing import Dict, Optional, List
from uuid import UUID

from sqlalchemy import func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import get_logger
from app.financial.cost.cost_models import CostEvent, UsageQuota
from app.financial.cost.cost_enums import CostEventType, CostProvider

logger = get_logger(__name__)


class CostTracker:
    """
    Service for tracking cost events and calculating costs.
    
    This provides the foundation for:
    - Real-time cost visibility
    - Budget alerts
    - Usage-based billing (future)
    - Cost optimization
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
        Track a cost event.
        
        Args:
            db: Database session
            user_id: User who generated the cost
            event_type: Type of cost event
            quantity: Number of units (characters, API calls, etc.)
            unit_cost: Cost per unit in USD
            provider: External provider (if applicable)
            metadata: Additional context
        
        Returns:
            Created CostEvent
        """
        total_cost = quantity * unit_cost
        
        event = CostEvent(
            user_id=user_id,
            event_type=event_type,
            provider=provider or CostProvider.INTERNAL,
            quantity=quantity,
            unit_cost=unit_cost,
            total_cost=total_cost,
            metadata=metadata or {},
        )
        
        db.add(event)
        await db.commit()
        await db.refresh(event)
        
        logger.info(
            f"Cost event tracked: user={user_id}, "
            f"type={event_type}, "
            f"quantity={quantity}, "
            f"cost=${total_cost:.4f}"
        )
        
        return event
    
    @staticmethod
    async def track_estimate(
        db: AsyncSession,
        user_id: UUID,
        event_type: CostEventType,
        quantity: float,
        unit_cost: float,
    ) -> float:
        """
        Calculate estimated cost without tracking.
        
        Useful for:
        - Pre-flight cost checks
        - Quote generation
        - Budget warnings
        
        Args:
            db: Database session
            user_id: User requesting estimate
            event_type: Type of operation
            quantity: Number of units
            unit_cost: Cost per unit
        
        Returns:
            Estimated cost in USD
        """
        estimated_cost = quantity * unit_cost
        
        logger.debug(
            f"Cost estimate: user={user_id}, "
            f"type={event_type}, "
            f"quantity={quantity}, "
            f"estimated=${estimated_cost:.4f}"
        )
        
        return estimated_cost
    
    @staticmethod
    async def get_user_monthly_cost(
        db: AsyncSession,
        user_id: UUID,
        month: Optional[datetime] = None,
    ) -> Dict:
        """
        Get total cost for a user in a given month.
        
        Args:
            db: Database session
            user_id: User ID
            month: Month to query (defaults to current month)
        
        Returns:
            Dict with total cost and breakdown by event type
        """
        if month is None:
            month = datetime.utcnow()
        
        # Calculate month boundaries
        month_start = month.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        
        if month.month == 12:
            month_end = month_start.replace(year=month.year + 1, month=1)
        else:
            month_end = month_start.replace(month=month.month + 1)
        
        # Query total cost
        total_result = await db.execute(
            func.sum(CostEvent.total_cost).filter(
                and_(
                    CostEvent.user_id == user_id,
                    CostEvent.created_at >= month_start,
                    CostEvent.created_at < month_end,
                )
            )
        )
        total_cost = total_result.scalar() or 0.0
        
        # Query breakdown by event type
        breakdown_result = await db.execute(
            db.query(
                CostEvent.event_type,
                func.sum(CostEvent.total_cost).label("cost"),
                func.count(CostEvent.id).label("count"),
            )
            .filter(
                and_(
                    CostEvent.user_id == user_id,
                    CostEvent.created_at >= month_start,
                    CostEvent.created_at < month_end,
                )
            )
            .group_by(CostEvent.event_type)
        )
        
        breakdown = {
            row.event_type: {
                "cost": float(row.cost),
                "count": row.count,
            }
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
        """
        Get total system cost for a given month.
        
        Args:
            db: Database session
            month: Month to query (defaults to current month)
        
        Returns:
            Dict with total cost and breakdown
        """
        if month is None:
            month = datetime.utcnow()
        
        # Calculate month boundaries
        month_start = month.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        
        if month.month == 12:
            month_end = month_start.replace(year=month.year + 1, month=1)
        else:
            month_end = month_start.replace(month=month.month + 1)
        
        # Query total cost
        total_result = await db.execute(
            func.sum(CostEvent.total_cost).filter(
                and_(
                    CostEvent.created_at >= month_start,
                    CostEvent.created_at < month_end,
                )
            )
        )
        total_cost = total_result.scalar() or 0.0
        
        # Query breakdown by event type
        breakdown_result = await db.execute(
            db.query(
                CostEvent.event_type,
                func.sum(CostEvent.total_cost).label("cost"),
                func.count(CostEvent.id).label("count"),
            )
            .filter(
                and_(
                    CostEvent.created_at >= month_start,
                    CostEvent.created_at < month_end,
                )
            )
            .group_by(CostEvent.event_type)
        )
        
        breakdown = {
            row.event_type: {
                "cost": float(row.cost),
                "count": row.count,
            }
            for row in breakdown_result
        }
        
        # Query by provider
        provider_result = await db.execute(
            db.query(
                CostEvent.provider,
                func.sum(CostEvent.total_cost).label("cost"),
            )
            .filter(
                and_(
                    CostEvent.created_at >= month_start,
                    CostEvent.created_at < month_end,
                )
            )
            .group_by(CostEvent.provider)
        )
        
        by_provider = {
            row.provider: float(row.cost)
            for row in provider_result
        }
        
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
        """
        Get daily cost trend for a user.
        
        Args:
            db: Database session
            user_id: User ID
            days: Number of days to look back
        
        Returns:
            List of daily cost totals
        """
        start_date = datetime.utcnow() - timedelta(days=days)
        
        result = await db.execute(
            db.query(
                func.date(CostEvent.created_at).label("date"),
                func.sum(CostEvent.total_cost).label("cost"),
            )
            .filter(
                and_(
                    CostEvent.user_id == user_id,
                    CostEvent.created_at >= start_date,
                )
            )
            .group_by(func.date(CostEvent.created_at))
            .order_by(func.date(CostEvent.created_at))
        )
        
        return [
            {
                "date": row.date.isoformat(),
                "cost": float(row.cost),
            }
            for row in result
        ]

"""
Billing Engine — Revenue & Usage Metrics Service
==================================================
Aggregates billing data for the internal metrics endpoint.

All queries run against the DB (usage_aggregate table) rather than Redis
so the metrics endpoint is consistent with persisted data.
"""
from __future__ import annotations

import uuid
from datetime import date
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.billing.models import UsageAggregate, WebhookEvent, SubscriptionAuditLog
from app.db.models.user import User


class BillingMetricsService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_summary(self) -> dict[str, Any]:
        today = date.today().isoformat()
        month = date.today().strftime("%Y-%m")

        today_totals = await self._period_totals("day", today)
        month_totals = await self._period_totals("month", month)
        subscriber_counts = await self._subscriber_counts()
        webhook_stats = await self._webhook_stats()
        top_users = await self._top_users_by_cost(month)

        return {
            "today": today_totals,
            "this_month": month_totals,
            "subscribers": subscriber_counts,
            "webhooks": webhook_stats,
            "top_users_by_cost": top_users,
            "generated_at": date.today().isoformat(),
        }

    async def get_user_usage(self, user_id: uuid.UUID) -> dict[str, Any]:
        today = date.today().isoformat()
        month = date.today().strftime("%Y-%m")

        day_row = await self._user_period(user_id, "day", today)
        month_row = await self._user_period(user_id, "month", month)

        return {
            "user_id": str(user_id),
            "today": self._row_to_dict(day_row),
            "this_month": self._row_to_dict(month_row),
        }

    # ── Internal ──────────────────────────────────────────────────────────────

    async def _period_totals(self, period_type: str, period_key: str) -> dict[str, Any]:
        result = await self._session.execute(
            select(
                func.sum(UsageAggregate.api_calls).label("api_calls"),
                func.sum(UsageAggregate.compute_ms).label("compute_ms"),
                func.sum(UsageAggregate.cost_usd).label("cost_usd"),
                func.count(UsageAggregate.user_id.distinct()).label("active_users"),
            ).where(
                UsageAggregate.period_type == period_type,
                UsageAggregate.period_key == period_key,
            )
        )
        row = result.one()
        return {
            "api_calls": int(row.api_calls or 0),
            "compute_ms": float(row.compute_ms or 0),
            "cost_usd": float(row.cost_usd or 0),
            "active_users": int(row.active_users or 0),
        }

    async def _subscriber_counts(self) -> dict[str, int]:
        result = await self._session.execute(
            select(User.subscription_status, func.count().label("cnt"))
            .group_by(User.subscription_status)
        )
        counts: dict[str, int] = {}
        for row in result:
            counts[row.subscription_status or "free"] = row.cnt
        return counts

    async def _webhook_stats(self) -> dict[str, int]:
        result = await self._session.execute(
            select(WebhookEvent.status, func.count().label("cnt"))
            .group_by(WebhookEvent.status)
        )
        return {row.status: row.cnt for row in result}

    async def _top_users_by_cost(self, month: str, limit: int = 10) -> list[dict]:
        result = await self._session.execute(
            select(
                UsageAggregate.user_id,
                UsageAggregate.api_calls,
                UsageAggregate.cost_usd,
            )
            .where(
                UsageAggregate.period_type == "month",
                UsageAggregate.period_key == month,
            )
            .order_by(UsageAggregate.cost_usd.desc())
            .limit(limit)
        )
        return [
            {"user_id": str(row.user_id), "api_calls": row.api_calls, "cost_usd": row.cost_usd}
            for row in result
        ]

    async def _user_period(
        self, user_id: uuid.UUID, period_type: str, period_key: str
    ) -> UsageAggregate | None:
        result = await self._session.execute(
            select(UsageAggregate).where(
                UsageAggregate.user_id == user_id,
                UsageAggregate.period_type == period_type,
                UsageAggregate.period_key == period_key,
            )
        )
        return result.scalar_one_or_none()

    @staticmethod
    def _row_to_dict(row: UsageAggregate | None) -> dict:
        if row is None:
            return {"api_calls": 0, "compute_ms": 0.0, "cost_usd": 0.0}
        return {
            "api_calls": row.api_calls,
            "compute_ms": row.compute_ms,
            "cost_usd": row.cost_usd,
        }

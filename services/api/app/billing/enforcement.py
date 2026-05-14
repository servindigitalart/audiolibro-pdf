"""
Billing Engine — Enforcement Service
======================================
Centralised quota enforcement logic.  Called by BillingEnforcementMiddleware
and directly by any endpoint that wants explicit quota checks.

Raises typed exceptions so callers can map them to the correct HTTP status.
"""
from __future__ import annotations

import uuid
from typing import Any

from app.billing.constants import (
    BILLABLE_STATUSES,
    TIER_DAILY_API_LIMITS,
    SubscriptionStatus,
)
from app.billing.usage_meter import UsageMeteringService


class QuotaExceeded(Exception):
    """Raised when a user has exhausted their daily API-call quota."""

    def __init__(self, user_id: uuid.UUID, limit: int, current: int) -> None:
        super().__init__(
            f"User {user_id} quota exceeded: {current}/{limit} API calls today"
        )
        self.user_id = user_id
        self.limit = limit
        self.current = current


class AccountSuspended(Exception):
    """Raised when the user's subscription status disallows API access."""

    def __init__(self, user_id: uuid.UUID, status: str) -> None:
        super().__init__(f"Account {user_id} is suspended (status={status!r})")
        self.user_id = user_id
        self.status = status


class BillingEnforcementService:
    """
    Checks whether a user is allowed to make an API call.

    Enforcement order:
      1. Status check — SUSPENDED / CANCELED → AccountSuspended
      2. Quota check  — daily API calls >= limit → QuotaExceeded
    """

    def __init__(self, redis: Any) -> None:
        self._meter = UsageMeteringService(redis)

    async def check(
        self,
        user_id: uuid.UUID,
        subscription_status: str,
        plan_tier: str,
    ) -> None:
        """
        Raises QuotaExceeded or AccountSuspended if the request should be blocked.
        Returns None if the request is permitted.
        """
        status = SubscriptionStatus(subscription_status)

        if status not in BILLABLE_STATUSES:
            raise AccountSuspended(user_id, subscription_status)

        limit = TIER_DAILY_API_LIMITS.get(plan_tier.upper(), TIER_DAILY_API_LIMITS["FREE"])
        if limit == -1:
            return  # unlimited

        today_usage = await self._meter.get_today(user_id)
        current = int(today_usage["api_calls"])
        if current >= limit:
            raise QuotaExceeded(user_id, limit, current)

"""
Revenue Protection Layer — Task 4
====================================
Prevents negative-margin users from draining infrastructure costs.

Protections:
  1. Daily cost cap per user (hard Redis-backed block)
  2. Monthly cost cap per user (hard block)
  3. Negative-margin detection (identifies paid users consuming more than revenue)
  4. Automatic throttle for high-cost free users (bot / abuse pattern)
  5. Anomaly spike detection (10× normal usage in a short window)

Design:
  - All state in Redis — no DB writes in the hot path
  - Redis keys have TTL so throttles auto-expire
  - RevenueProtectionService is stateless except for Redis dependency
  - Raises typed exceptions so HTTP layer can map to correct status codes

Redis key layout:
  pricing:throttle:{user_id}           → "1" (exists = throttled), TTL = throttle_ttl_seconds
  pricing:cost_cap_breached:{user_id}  → "1" (exists = cap hit today), TTL = seconds until midnight
  pricing:abuse_flag:{user_id}         → abuse_score (float), TTL = 24h
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta
from typing import Any

from app.pricing.tiers import TIER_CATALOG, PlanTier
from app.pricing.unit_economics import UnitEconomicsEngine, COST_RATES

logger = logging.getLogger(__name__)


# ── Exception types ───────────────────────────────────────────────────────────

class CostCapExceeded(Exception):
    """
    Raised when a user's daily or monthly cost cap is breached.
    Map to HTTP 402 or 429 at the API layer.
    """
    def __init__(self, user_id: str, cap_type: str, cost: float, cap: float) -> None:
        super().__init__(
            f"User {user_id} {cap_type} cost ${cost:.4f} exceeds cap ${cap:.4f}"
        )
        self.user_id = user_id
        self.cap_type = cap_type
        self.cost = cost
        self.cap = cap


class NegativeMarginThrottle(Exception):
    """
    Raised when a user is throttled due to negative-margin detection.
    Map to HTTP 429 with Retry-After header.
    """
    def __init__(self, user_id: str, retry_after_seconds: int = 3600) -> None:
        super().__init__(f"User {user_id} throttled: negative margin detected")
        self.user_id = user_id
        self.retry_after_seconds = retry_after_seconds


# ── Redis key helpers ─────────────────────────────────────────────────────────

def _throttle_key(user_id: str) -> str:
    return f"pricing:throttle:{user_id}"

def _daily_cap_key(user_id: str) -> str:
    return f"pricing:cost_cap_daily:{user_id}"

def _monthly_cap_key(user_id: str) -> str:
    return f"pricing:cost_cap_monthly:{user_id}"

def _abuse_flag_key(user_id: str) -> str:
    return f"pricing:abuse_flag:{user_id}"


def _seconds_until_midnight_utc() -> int:
    now = datetime.now(timezone.utc)
    tomorrow = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return max(1, int((tomorrow - now).total_seconds()))


# ── Service ───────────────────────────────────────────────────────────────────

class RevenueProtectionService:
    """
    Enforces cost caps and negative-margin throttling.

    All checks are O(1) Redis reads — designed to run in the request hot path
    after the billing enforcement middleware.
    """

    # How long to throttle a negative-margin free user (seconds)
    THROTTLE_TTL_FREE    = 3_600    # 1 hour
    THROTTLE_TTL_PAID    = 900      # 15 minutes (alert but recover quickly)

    # Abuse score threshold that triggers throttle
    ABUSE_SCORE_THRESHOLD = 10.0

    # Anomaly spike: flag if daily cost > this multiple of the tier's daily average
    SPIKE_MULTIPLE = 10.0

    def __init__(self, redis: Any) -> None:
        self._redis = redis
        self._engine = UnitEconomicsEngine(COST_RATES)

    # ── Check API (call in request hot path) ──────────────────────────────────

    async def check(
        self,
        user_id: str,
        tier: PlanTier | str,
        daily_cost_usd: float,
        monthly_cost_usd: float,
    ) -> None:
        """
        Enforce all revenue protection rules.

        Raises CostCapExceeded or NegativeMarginThrottle if the request should
        be blocked.  Returns None if the request is permitted.
        """
        if isinstance(tier, str):
            tier = PlanTier(tier.upper())

        config = TIER_CATALOG[tier]

        # 1. Daily cost cap
        if daily_cost_usd >= config.max_daily_cost_usd:
            await self._redis.setex(
                _daily_cap_key(user_id),
                _seconds_until_midnight_utc(),
                "1",
            )
            raise CostCapExceeded(user_id, "daily", daily_cost_usd, config.max_daily_cost_usd)

        # 2. Monthly cost cap
        if monthly_cost_usd >= config.max_monthly_cost_usd:
            raise CostCapExceeded(user_id, "monthly", monthly_cost_usd, config.max_monthly_cost_usd)

        # 3. Negative margin (paid tiers only — free tier expected to run at loss)
        if tier != PlanTier.FREE:
            if self._engine.is_negative_margin_user(tier, monthly_cost_usd):
                await self._apply_throttle(user_id, tier)
                raise NegativeMarginThrottle(user_id, retry_after_seconds=self.THROTTLE_TTL_PAID)

        # 4. Explicit throttle flag (set by abuse detection or previous cap breach)
        if await self._is_throttled(user_id):
            raise NegativeMarginThrottle(user_id)

    async def check_daily_only(
        self,
        user_id: str,
        tier: PlanTier | str,
        daily_cost_usd: float,
    ) -> None:
        """Lightweight daily-cap-only check for the hot path (skips monthly query)."""
        if isinstance(tier, str):
            tier = PlanTier(tier.upper())
        config = TIER_CATALOG[tier]
        if daily_cost_usd >= config.max_daily_cost_usd:
            raise CostCapExceeded(user_id, "daily", daily_cost_usd, config.max_daily_cost_usd)

    # ── Anomaly detection ─────────────────────────────────────────────────────

    async def record_abuse_signal(
        self,
        user_id: str,
        score_delta: float = 1.0,
    ) -> float:
        """
        Increment the abuse score for a user and return the new total.

        score_delta values:
          1.0  — one anomalous request (rate limit hit, suspicious UA, etc.)
          5.0  — severe signal (scraping pattern, credential stuffing attempt)
         10.0  — critical (immediate throttle)
        """
        key = _abuse_flag_key(user_id)
        new_score = await self._redis.incrbyfloat(key, score_delta)
        await self._redis.expire(key, 86_400)  # 24h TTL

        if new_score >= self.ABUSE_SCORE_THRESHOLD:
            ttl = self.THROTTLE_TTL_FREE
            await self._apply_throttle(user_id, PlanTier.FREE, ttl=ttl)
            logger.warning(
                "revenue_protection_throttle",
                extra={"user_id": user_id, "abuse_score": new_score},
            )

        return new_score

    async def get_abuse_score(self, user_id: str) -> float:
        raw = await self._redis.get(_abuse_flag_key(user_id))
        return float(raw) if raw else 0.0

    async def clear_throttle(self, user_id: str) -> None:
        """Admin action: remove a user's throttle flag."""
        await self._redis.delete(_throttle_key(user_id))

    async def clear_abuse_score(self, user_id: str) -> None:
        """Admin action: reset a user's abuse score."""
        await self._redis.delete(_abuse_flag_key(user_id))

    def is_spike(self, tier: PlanTier | str, daily_cost_usd: float) -> bool:
        """
        Return True if today's cost is anomalously high compared to the daily budget.

        Uses SPIKE_MULTIPLE × (monthly_cap / 30) as the expected daily spend.
        """
        if isinstance(tier, str):
            tier = PlanTier(tier.upper())
        config = TIER_CATALOG[tier]
        expected_daily = config.max_monthly_cost_usd / 30.0
        return daily_cost_usd > expected_daily * self.SPIKE_MULTIPLE

    # ── Internal helpers ──────────────────────────────────────────────────────

    async def _apply_throttle(
        self,
        user_id: str,
        tier: PlanTier,
        ttl: int | None = None,
    ) -> None:
        ttl = ttl or (
            self.THROTTLE_TTL_PAID if tier != PlanTier.FREE else self.THROTTLE_TTL_FREE
        )
        await self._redis.setex(_throttle_key(user_id), ttl, "1")

    async def _is_throttled(self, user_id: str) -> bool:
        result = await self._redis.exists(_throttle_key(user_id))
        return bool(result)

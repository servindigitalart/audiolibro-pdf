"""
Billing Engine — Usage Metering Service
========================================
Dual-write architecture:
  - Hot path: Redis HINCRBY (atomic, O(1), sub-millisecond)
  - Persistence: PostgreSQL UPSERT on flush (survives Redis eviction)

Redis key layout:
  billing:usage:{user_id}:{YYYY-MM-DD}  → hash {api_calls, compute_ms, cost_usd}
  billing:usage:{user_id}:{YYYY-MM}     → hash {api_calls, compute_ms, cost_usd}
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.billing.constants import USAGE_HOT_KEY, USAGE_MONTH_KEY

# USD rates (same constants used in performance instrumentation)
_DB_QUERY_USD: float = 1e-6
_REDIS_OP_USD: float = 5e-8
_COMPUTE_PER_MS_USD: float = 3e-8


class UsageMeteringService:
    """
    Records per-request usage atomically in Redis and persists to PostgreSQL.

    All methods are safe to call concurrently — Redis is single-threaded and
    SQLAlchemy upserts use ON CONFLICT DO UPDATE.
    """

    def __init__(self, redis: Any) -> None:
        self._redis = redis

    # ── Hot-path increment (called on every metered request) ─────────────────

    async def record(
        self,
        user_id: uuid.UUID,
        *,
        api_calls: int = 1,
        compute_ms: float = 0.0,
        db_queries: int = 0,
        redis_ops: int = 0,
    ) -> None:
        today = date.today().isoformat()             # YYYY-MM-DD
        month = date.today().strftime("%Y-%m")       # YYYY-MM

        cost = (
            api_calls * 0.0
            + db_queries * _DB_QUERY_USD
            + redis_ops * _REDIS_OP_USD
            + compute_ms * _COMPUTE_PER_MS_USD
        )

        uid = str(user_id)
        day_key   = USAGE_HOT_KEY.format(user_id=uid, date=today)
        month_key = USAGE_MONTH_KEY.format(user_id=uid, month=month)

        pipe = self._redis.pipeline()
        pipe.hincrby(day_key, "api_calls", api_calls)
        pipe.hincrbyfloat(day_key, "compute_ms", compute_ms)
        pipe.hincrbyfloat(day_key, "cost_usd", cost)
        pipe.hincrby(month_key, "api_calls", api_calls)
        pipe.hincrbyfloat(month_key, "compute_ms", compute_ms)
        pipe.hincrbyfloat(month_key, "cost_usd", cost)
        await pipe.execute()

    # ── Read helpers ──────────────────────────────────────────────────────────

    async def get_today(self, user_id: uuid.UUID) -> dict[str, float]:
        today = date.today().isoformat()
        key = USAGE_HOT_KEY.format(user_id=str(user_id), date=today)
        raw = await self._redis.hgetall(key)
        return {
            "api_calls": float(raw.get("api_calls", 0)),
            "compute_ms": float(raw.get("compute_ms", 0)),
            "cost_usd": float(raw.get("cost_usd", 0)),
        }

    async def get_month(self, user_id: uuid.UUID) -> dict[str, float]:
        month = date.today().strftime("%Y-%m")
        key = USAGE_MONTH_KEY.format(user_id=str(user_id), month=month)
        raw = await self._redis.hgetall(key)
        return {
            "api_calls": float(raw.get("api_calls", 0)),
            "compute_ms": float(raw.get("compute_ms", 0)),
            "cost_usd": float(raw.get("cost_usd", 0)),
        }

    # ── Persistence flush (called by background task or teardown) ─────────────

    async def flush_to_db(
        self,
        session: AsyncSession,
        user_id: uuid.UUID,
        *,
        period_type: str,
        period_key: str,
    ) -> None:
        """Upsert Redis usage data into usage_aggregate."""
        uid = str(user_id)
        if period_type == "day":
            redis_key = USAGE_HOT_KEY.format(user_id=uid, date=period_key)
        else:
            redis_key = USAGE_MONTH_KEY.format(user_id=uid, month=period_key)

        raw = await self._redis.hgetall(redis_key)
        if not raw:
            return

        api_calls  = int(float(raw.get("api_calls", 0)))
        compute_ms = float(raw.get("compute_ms", 0))
        cost_usd   = float(raw.get("cost_usd", 0))

        await session.execute(
            text("""
                INSERT INTO usage_aggregate
                    (id, user_id, period_type, period_key, api_calls, compute_ms, cost_usd, updated_at)
                VALUES
                    (gen_random_uuid(), :user_id, :period_type, :period_key,
                     :api_calls, :compute_ms, :cost_usd, now())
                ON CONFLICT (user_id, period_type, period_key)
                DO UPDATE SET
                    api_calls  = EXCLUDED.api_calls,
                    compute_ms = EXCLUDED.compute_ms,
                    cost_usd   = EXCLUDED.cost_usd,
                    updated_at = now()
            """),
            {
                "user_id": str(user_id),
                "period_type": period_type,
                "period_key": period_key,
                "api_calls": api_calls,
                "compute_ms": compute_ms,
                "cost_usd": cost_usd,
            },
        )
        await session.commit()

"""
Usage Metering Service Tests
=============================
Tests atomic Redis increments, daily/monthly rollups, and DB persistence.
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import date

import pytest

from app.billing.usage_meter import UsageMeteringService
from app.billing.constants import USAGE_HOT_KEY, USAGE_MONTH_KEY




async def test_record_increments_daily_api_calls(fake_redis, user_id):
    svc = UsageMeteringService(fake_redis)
    await svc.record(user_id, api_calls=1)
    await svc.record(user_id, api_calls=1)

    today_data = await svc.get_today(user_id)
    assert today_data["api_calls"] == 2.0


async def test_record_increments_monthly_api_calls(fake_redis, user_id):
    svc = UsageMeteringService(fake_redis)
    await svc.record(user_id, api_calls=5)

    month_data = await svc.get_month(user_id)
    assert month_data["api_calls"] == 5.0


async def test_record_accumulates_compute_ms(fake_redis, user_id):
    svc = UsageMeteringService(fake_redis)
    await svc.record(user_id, compute_ms=10.5)
    await svc.record(user_id, compute_ms=20.0)

    today_data = await svc.get_today(user_id)
    assert abs(today_data["compute_ms"] - 30.5) < 0.01


async def test_record_accumulates_cost(fake_redis, user_id):
    svc = UsageMeteringService(fake_redis)
    await svc.record(user_id, db_queries=2, redis_ops=9, compute_ms=50.0)

    today_data = await svc.get_today(user_id)
    assert today_data["cost_usd"] > 0.0


async def test_different_users_are_isolated(fake_redis):
    svc = UsageMeteringService(fake_redis)
    uid_a = uuid.uuid4()
    uid_b = uuid.uuid4()

    await svc.record(uid_a, api_calls=10)
    await svc.record(uid_b, api_calls=3)

    a_data = await svc.get_today(uid_a)
    b_data = await svc.get_today(uid_b)

    assert a_data["api_calls"] == 10.0
    assert b_data["api_calls"] == 3.0


async def test_concurrent_increments_are_consistent(fake_redis, user_id):
    """asyncio is single-threaded — no actual race, but verifies accumulation correctness."""
    svc = UsageMeteringService(fake_redis)
    N = 100

    await asyncio.gather(*[svc.record(user_id, api_calls=1) for _ in range(N)])

    today_data = await svc.get_today(user_id)
    assert today_data["api_calls"] == float(N)


async def test_get_today_returns_zeros_for_unknown_user(fake_redis):
    svc = UsageMeteringService(fake_redis)
    data = await svc.get_today(uuid.uuid4())
    assert data == {"api_calls": 0.0, "compute_ms": 0.0, "cost_usd": 0.0}


async def test_get_month_returns_zeros_for_unknown_user(fake_redis):
    svc = UsageMeteringService(fake_redis)
    data = await svc.get_month(uuid.uuid4())
    assert data == {"api_calls": 0.0, "compute_ms": 0.0, "cost_usd": 0.0}


async def test_flush_to_db_upserts_usage(fake_redis, db_session, db_user):
    """Flush Redis usage data into the usage_aggregate table."""
    from app.billing.models import UsageAggregate
    from sqlalchemy import select

    svc = UsageMeteringService(fake_redis)
    await svc.record(db_user.id, api_calls=42, compute_ms=100.0)

    today = date.today().isoformat()
    await svc.flush_to_db(db_session, db_user.id, period_type="day", period_key=today)

    result = await db_session.execute(
        select(UsageAggregate).where(
            UsageAggregate.user_id == db_user.id,
            UsageAggregate.period_type == "day",
            UsageAggregate.period_key == today,
        )
    )
    row = result.scalar_one_or_none()
    assert row is not None
    assert row.api_calls == 42


async def test_flush_to_db_upsert_is_idempotent(fake_redis, db_session, db_user):
    """Flushing twice must not double-count."""
    svc = UsageMeteringService(fake_redis)
    await svc.record(db_user.id, api_calls=10)

    today = date.today().isoformat()
    await svc.flush_to_db(db_session, db_user.id, period_type="day", period_key=today)
    await svc.flush_to_db(db_session, db_user.id, period_type="day", period_key=today)

    from app.billing.models import UsageAggregate
    from sqlalchemy import select, func

    result = await db_session.execute(
        select(func.count()).select_from(UsageAggregate).where(
            UsageAggregate.user_id == db_user.id,
            UsageAggregate.period_type == "day",
            UsageAggregate.period_key == today,
        )
    )
    assert result.scalar_one() == 1  # Only one row, not two

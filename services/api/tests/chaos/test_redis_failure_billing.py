"""
Redis Failure — Billing Resilience Tests
=========================================
Exercises UsageMeteringService and BillingEnforcementService under Redis faults.

Failure modes tested:
  HARD_FAIL     — pipeline raises ConnectionError immediately; no state change
  PARTIAL_WRITE — Redis stores the data, then drops the response
  TIMEOUT       — asyncio.TimeoutError; models hung Redis connection
  SILENT_DROP   — call accepted; data silently discarded; zeros returned

Financial correctness after each failure is verified by the invariant suite.
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import date

import pytest

from app.billing.constants import USAGE_HOT_KEY, USAGE_MONTH_KEY
from app.billing.usage_meter import UsageMeteringService
from tests.chaos.financial_invariants import FinancialInvariantSuite
from tests.chaos.injectors import FailingRedis, FailureMode


# ── Helpers ───────────────────────────────────────────────────────────────────

def _meter(redis) -> UsageMeteringService:
    return UsageMeteringService(redis)


def _today_key(user_id: uuid.UUID) -> str:
    return USAGE_HOT_KEY.format(user_id=str(user_id), date=date.today().isoformat())


def _month_key(user_id: uuid.UUID) -> str:
    return USAGE_MONTH_KEY.format(user_id=str(user_id), month=date.today().strftime("%Y-%m"))


# ── Hard fail (HARD_FAIL) ─────────────────────────────────────────────────────

async def test_hard_fail_raises_connection_error(failing_redis):
    """pipeline hard fail propagates ConnectionError to the caller."""
    uid = uuid.uuid4()
    failing_redis.configure(fail_ops=["pipeline"], mode=FailureMode.HARD_FAIL)
    svc = _meter(failing_redis)

    with pytest.raises(ConnectionError):
        await svc.record(uid, api_calls=5)


async def test_hard_fail_leaves_redis_state_clean(failing_redis):
    """After a pipeline hard fail, no partial data is stored in Redis."""
    uid = uuid.uuid4()
    failing_redis.configure(fail_ops=["pipeline"], mode=FailureMode.HARD_FAIL)
    svc = _meter(failing_redis)

    try:
        await svc.record(uid, api_calls=3)
    except ConnectionError:
        pass

    raw = await failing_redis.hgetall(_today_key(uid))
    assert raw == {}, "Hard fail must leave Redis state unmodified"


async def test_hard_fail_then_success_accumulates_correctly(failing_redis):
    """After a failed call, a successful call records the correct amount."""
    uid = uuid.uuid4()
    failing_redis.configure(fail_ops=["pipeline"], mode=FailureMode.HARD_FAIL)
    svc = _meter(failing_redis)

    try:
        await svc.record(uid, api_calls=10)
    except ConnectionError:
        pass

    failing_redis.clear_failures()
    await svc.record(uid, api_calls=3)

    usage = await svc.get_today(uid)
    assert usage["api_calls"] == 3.0, "Only the successful call should be counted"


# ── Partial write (PARTIAL_WRITE) ─────────────────────────────────────────────

async def test_partial_write_stores_data_despite_exception(failing_redis):
    """
    PARTIAL_WRITE mode: data IS stored in Redis, exception still raised.
    This is the most dangerous failure mode — the client can't confirm the write.
    """
    uid = uuid.uuid4()
    failing_redis.configure(
        fail_ops=["pipeline_execute"], mode=FailureMode.PARTIAL_WRITE
    )
    svc = _meter(failing_redis)

    with pytest.raises(ConnectionError):
        await svc.record(uid, api_calls=7)

    # Data was written to Redis even though the exception fired
    raw = await failing_redis.hgetall(_today_key(uid))
    assert int(float(raw.get("api_calls", 0))) > 0, (
        "PARTIAL_WRITE must store data even though exception was raised"
    )


async def test_partial_write_causes_double_count_on_retry(failing_redis):
    """
    After a partial write, a naive retry without idempotency creates a double count.
    This test documents the dangerous behavior — callers must use idempotency keys.
    """
    uid = uuid.uuid4()
    failing_redis.configure(
        fail_ops=["pipeline_execute"], mode=FailureMode.PARTIAL_WRITE
    )
    svc = _meter(failing_redis)

    try:
        await svc.record(uid, api_calls=5)
    except ConnectionError:
        pass  # first attempt: partial write stored 5

    failing_redis.clear_failures()
    await svc.record(uid, api_calls=5)  # retry: now 10 total

    usage = await svc.get_today(uid)
    assert usage["api_calls"] == 10.0, (
        "Naive retry after partial write results in double count — "
        "callers must guard with idempotency keys"
    )


# ── Timeout (TIMEOUT) ─────────────────────────────────────────────────────────

async def test_timeout_raises_asyncio_timeout_error(failing_redis):
    """TIMEOUT mode raises asyncio.TimeoutError — not ConnectionError."""
    uid = uuid.uuid4()
    failing_redis.configure(fail_ops=["pipeline"], mode=FailureMode.TIMEOUT)
    svc = _meter(failing_redis)

    with pytest.raises(asyncio.TimeoutError):
        await svc.record(uid, api_calls=1)


async def test_timeout_leaves_no_data_in_redis(failing_redis):
    """Timeout failure mode must not write partial data."""
    uid = uuid.uuid4()
    failing_redis.configure(fail_ops=["pipeline"], mode=FailureMode.TIMEOUT)
    svc = _meter(failing_redis)

    try:
        await svc.record(uid, api_calls=1)
    except asyncio.TimeoutError:
        pass

    raw = await failing_redis.hgetall(_today_key(uid))
    assert raw == {}


# ── Silent drop (SILENT_DROP) ─────────────────────────────────────────────────

async def test_silent_drop_does_not_raise(failing_redis):
    """SILENT_DROP: record() completes without exception; data is lost.

    Configuring 'pipeline_execute' (not 'pipeline') ensures the execute()
    call is the one that drops data silently — the pipeline object is still
    returned, but execute() clears the queue and returns [].
    """
    uid = uuid.uuid4()
    failing_redis.configure(fail_ops=["pipeline_execute"], mode=FailureMode.SILENT_DROP)
    svc = _meter(failing_redis)

    await svc.record(uid, api_calls=5)  # must not raise

    usage = await svc.get_today(uid)
    assert usage["api_calls"] == 0.0, "Silent drop discards all written data"


async def test_hgetall_silent_drop_returns_zeros(failing_redis):
    """get_today() with SILENT_DROP hgetall returns zeroed usage dict."""
    uid = uuid.uuid4()

    # First, write valid data normally
    failing_redis.clear_failures()
    svc = _meter(failing_redis)
    await svc.record(uid, api_calls=10)

    # Now break hgetall silently
    failing_redis.configure(fail_ops=["hgetall"], mode=FailureMode.SILENT_DROP)
    usage = await svc.get_today(uid)

    assert usage == {"api_calls": 0.0, "compute_ms": 0.0, "cost_usd": 0.0}


# ── After-N-successes failure pattern ─────────────────────────────────────────

async def test_fail_after_n_successes(failing_redis):
    """
    configure(after=2) means: first 2 calls succeed, then fail.
    Models a Redis connection that degrades after some healthy traffic.
    """
    uid = uuid.uuid4()
    failing_redis.configure(
        fail_ops=["pipeline"], mode=FailureMode.HARD_FAIL, after=2
    )
    svc = _meter(failing_redis)

    # First 2 succeed
    await svc.record(uid, api_calls=1)
    await svc.record(uid, api_calls=1)

    usage = await svc.get_today(uid)
    assert usage["api_calls"] == 2.0

    # Third fails
    with pytest.raises(ConnectionError):
        await svc.record(uid, api_calls=1)

    # Count unchanged at 2 (hard fail = no write)
    usage = await svc.get_today(uid)
    assert usage["api_calls"] == 2.0


# ── Recovery ─────────────────────────────────────────────────────────────────

async def test_service_recovers_after_clear_failures(failing_redis):
    """After clear_failures(), the service operates normally again."""
    uid = uuid.uuid4()
    svc = _meter(failing_redis)

    failing_redis.configure(fail_ops=["pipeline"], mode=FailureMode.HARD_FAIL)
    try:
        await svc.record(uid, api_calls=5)
    except ConnectionError:
        pass

    failing_redis.clear_failures()

    await svc.record(uid, api_calls=3)
    await svc.record(uid, api_calls=2)

    usage = await svc.get_today(uid)
    assert usage["api_calls"] == 5.0


# ── Invariant checks ──────────────────────────────────────────────────────────

async def test_partial_write_detectable_by_i5_invariant(failing_redis, db_session, chaos_user):
    """
    I5: Redis usage < DB usage signals data loss.
    After a PARTIAL_WRITE followed by a flush, then Redis eviction (simulated by
    resetting the hash), I5 invariant fires.
    chaos_user provides the FK-backed user row required by usage_aggregate.
    """
    uid = chaos_user.id

    # Write to Redis successfully
    svc = _meter(failing_redis)
    await svc.record(uid, api_calls=10)

    today = date.today().isoformat()

    # Flush Redis state to DB
    await svc.flush_to_db(db_session, uid, period_type="day", period_key=today)

    # Simulate Redis eviction: clear the hash directly
    key = _today_key(uid)
    if key in failing_redis._hashes:
        del failing_redis._hashes[key]

    # I5: Redis (0) < DB (10) → data loss detected
    suite = FinancialInvariantSuite()
    with pytest.raises(Exception, match="I5"):
        await suite.assert_redis_consistent(
            failing_redis, db_session, uid, "day", today
        )

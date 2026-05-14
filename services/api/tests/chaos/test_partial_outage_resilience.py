"""
Partial Outage Resilience Tests
================================
Tests financial correctness when subsystems fail partially:
  - Redis hard down while DB is healthy
  - Redis PARTIAL_WRITE with DB flush verification
  - DB slow/unavailable with Redis healthy
  - Both systems recovering after outage

All scenarios verify that financial invariants (I1–I6) hold throughout.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import insert, select, text, update

from app.billing.constants import USAGE_HOT_KEY, USAGE_MONTH_KEY, SubscriptionStatus
from app.billing.models import IdempotencyKey, SubscriptionAuditLog, UsageAggregate
from app.billing.subscription import SubscriptionService
from app.billing.usage_meter import UsageMeteringService
from tests.chaos.financial_invariants import FinancialInvariantSuite
from tests.chaos.injectors import (
    ChaosOrchestrator,
    FailingRedis,
    FailureMode,
    inject_commit_failure,
    inject_execute_failure,
)
from tests.fakes import FakeRedis


# ── Redis hard down ───────────────────────────────────────────────────────────

async def test_redis_hard_down_usage_record_raises(failing_redis):
    """With Redis hard down, record() raises ConnectionError immediately."""
    uid = uuid.uuid4()
    failing_redis.configure(fail_ops=["pipeline"], mode=FailureMode.HARD_FAIL)
    svc = UsageMeteringService(failing_redis)

    with pytest.raises(ConnectionError):
        await svc.record(uid, api_calls=1)


async def test_redis_hard_down_get_today_raises(failing_redis):
    """With hgetall failing hard, get_today() propagates the error."""
    uid = uuid.uuid4()
    failing_redis.configure(fail_ops=["hgetall"], mode=FailureMode.HARD_FAIL)
    svc = UsageMeteringService(failing_redis)

    with pytest.raises(ConnectionError):
        await svc.get_today(uid)


async def test_redis_silent_drop_get_today_returns_zeros(failing_redis):
    """
    SILENT_DROP on hgetall: get_today() returns zeroed dict without raising.
    This models a Redis partition where reads fail silently — billing
    continues but usage reads are degraded.
    """
    uid = uuid.uuid4()

    # Write valid data first
    failing_redis.clear_failures()
    svc = UsageMeteringService(failing_redis)
    await svc.record(uid, api_calls=5)

    # Now degrade reads silently
    failing_redis.configure(fail_ops=["hgetall"], mode=FailureMode.SILENT_DROP)
    usage = await svc.get_today(uid)
    assert usage == {"api_calls": 0.0, "compute_ms": 0.0, "cost_usd": 0.0}


async def test_redis_recovery_after_hard_fail(failing_redis):
    """After Redis recovery (clear_failures), service operates correctly."""
    uid = uuid.uuid4()
    svc = UsageMeteringService(failing_redis)

    # Fail
    failing_redis.configure(fail_ops=["pipeline"], mode=FailureMode.HARD_FAIL)
    try:
        await svc.record(uid, api_calls=10)
    except ConnectionError:
        pass

    # Recover
    failing_redis.clear_failures()
    await svc.record(uid, api_calls=5)
    await svc.record(uid, api_calls=3)

    usage = await svc.get_today(uid)
    assert usage["api_calls"] == 8.0, "After recovery, only successful calls counted"


# ── Redis PARTIAL_WRITE + flush verification ──────────────────────────────────

async def test_partial_write_data_persists_in_redis(failing_redis):
    """
    PARTIAL_WRITE: Redis stores the data before raising.
    After the exception, the key exists in Redis with the incremented value.
    """
    uid = uuid.uuid4()
    today = date.today().isoformat()
    failing_redis.configure(
        fail_ops=["pipeline_execute"], mode=FailureMode.PARTIAL_WRITE
    )
    svc = UsageMeteringService(failing_redis)

    with pytest.raises(ConnectionError):
        await svc.record(uid, api_calls=7)

    key = USAGE_HOT_KEY.format(user_id=str(uid), date=today)
    raw = await failing_redis.hgetall(key)
    assert int(float(raw.get("api_calls", 0))) == 7, (
        "PARTIAL_WRITE must store data in Redis despite raising"
    )


async def test_flush_after_partial_write_is_consistent(failing_redis, db_session, chaos_user):
    """
    After a partial write, flush_to_db reads the (partially written) Redis value
    and persists it. The DB reflects what Redis has — no data corruption.
    chaos_user provides the FK-backed row required by usage_aggregate.
    """
    uid = chaos_user.id
    today = date.today().isoformat()

    svc = UsageMeteringService(failing_redis)

    # First, normal record
    await svc.record(uid, api_calls=5)

    # Partial write on second record: data IS stored in Redis before exception
    failing_redis.configure(
        fail_ops=["pipeline_execute"], mode=FailureMode.PARTIAL_WRITE, after=0
    )
    try:
        await svc.record(uid, api_calls=3)
    except ConnectionError:
        pass  # Partial write happened — Redis now has some data

    # Flush Redis → DB
    failing_redis.clear_failures()
    await svc.flush_to_db(db_session, uid, period_type="day", period_key=today)

    result = await db_session.execute(
        select(UsageAggregate.api_calls).where(
            UsageAggregate.user_id == uid,
            UsageAggregate.period_type == "day",
            UsageAggregate.period_key == today,
        )
    )
    db_calls = result.scalar_one()
    redis_raw = await failing_redis.hgetall(
        USAGE_HOT_KEY.format(user_id=str(uid), date=today)
    )
    redis_calls = int(float(redis_raw.get("api_calls", 0)))

    assert db_calls == redis_calls, (
        f"After flush, DB ({db_calls}) must equal Redis ({redis_calls})"
    )


async def test_i5_invariant_fires_on_redis_eviction(failing_redis, db_session, chaos_user):
    """
    I5 invariant: if Redis is cleared after a flush, Redis < DB → data loss detected.
    chaos_user provides the FK row required by usage_aggregate.
    """
    uid = chaos_user.id
    today = date.today().isoformat()

    svc = UsageMeteringService(failing_redis)
    await svc.record(uid, api_calls=10)
    await svc.flush_to_db(db_session, uid, period_type="day", period_key=today)

    # Simulate Redis eviction: delete the hash key
    key = USAGE_HOT_KEY.format(user_id=str(uid), date=today)
    if key in failing_redis._hashes:
        del failing_redis._hashes[key]

    suite = FinancialInvariantSuite()
    with pytest.raises(Exception, match="I5"):
        await suite.assert_redis_consistent(failing_redis, db_session, uid, "day", today)


# ── DB partial outage ─────────────────────────────────────────────────────────

async def test_flush_to_db_execute_failure_does_not_corrupt_redis(db_session, failing_redis):
    """
    When flush_to_db fails because execute() raises, Redis data is unmodified.
    The flush can be safely retried.
    """
    uid = uuid.uuid4()
    today = date.today().isoformat()

    svc = UsageMeteringService(failing_redis)
    await svc.record(uid, api_calls=4)

    async with inject_execute_failure(db_session, after=0) as patched:
        with pytest.raises(RuntimeError, match="CHAOS"):
            await svc.flush_to_db(patched, uid, period_type="day", period_key=today)

    # Redis still intact
    usage = await svc.get_today(uid)
    assert usage["api_calls"] == 4.0


async def test_flush_to_db_commit_failure_does_not_corrupt_redis(db_session, failing_redis, chaos_user):
    """
    When flush_to_db fails at commit, Redis data is unmodified.
    The flush can be safely retried.
    chaos_user provides the FK row required by usage_aggregate INSERT.
    """
    uid = chaos_user.id
    today = date.today().isoformat()

    svc = UsageMeteringService(failing_redis)
    await svc.record(uid, api_calls=6)

    async with inject_commit_failure(db_session, after=0) as patched:
        with pytest.raises(RuntimeError, match="CHAOS"):
            await svc.flush_to_db(patched, uid, period_type="day", period_key=today)

    await db_session.rollback()

    usage = await svc.get_today(uid)
    assert usage["api_calls"] == 6.0


# ── Invariant validation against manually corrupted state ────────────────────

async def test_i2_invariant_fires_on_negative_usage(db_session, chaos_user, invariants):
    """
    I2: Manually inserting a row with negative api_calls triggers the invariant.
    This tests that the invariant checker itself works correctly.
    """
    today = date.today().isoformat()
    await db_session.execute(
        text("""
            INSERT INTO usage_aggregate
                (id, user_id, period_type, period_key, api_calls, compute_ms, cost_usd, updated_at)
            VALUES
                (gen_random_uuid(), :uid, 'day', :pk, -1, 0, 0, now())
        """),
        {"uid": str(chaos_user.id), "pk": today},
    )
    await db_session.flush()

    with pytest.raises(Exception, match="I2"):
        await invariants.assert_all(db_session)


async def test_i3_invariant_fires_on_invalid_transition_in_log(db_session, chaos_user, invariants):
    """
    I3: Manually inserting an invalid transition into audit_log triggers the invariant.
    Simulates a direct DB write that bypassed the state machine.
    """
    await db_session.execute(
        insert(SubscriptionAuditLog).values(
            user_id=chaos_user.id,
            from_status="free",   # free → canceled is NOT in VALID_TRANSITIONS
            to_status="canceled",
            actor="chaos_test",
        )
    )
    await db_session.flush()

    with pytest.raises(Exception, match="I3"):
        await invariants.assert_all(db_session)


async def test_i6_invariant_fires_on_stuck_lock(db_session, chaos_user, invariants):
    """
    I6: A lock older than max_age_hours is flagged as stuck.
    This simulates an operation that was never completed or failed.
    """
    old_time = datetime.now(timezone.utc) - timedelta(hours=3)

    await db_session.execute(
        insert(IdempotencyKey).values(
            idempotency_key=f"stuck_{uuid.uuid4().hex}",
            user_id=chaos_user.id,
            status="locked",
            expires_at=datetime.now(timezone.utc) + timedelta(days=7),
            created_at=old_time,
        )
    )
    await db_session.flush()

    with pytest.raises(Exception, match="I6"):
        await invariants.assert_all(db_session, stuck_lock_max_age_hours=1.0)


# ── ChaosOrchestrator ─────────────────────────────────────────────────────────

async def test_chaos_orchestrator_redis_hard_down(db_session, chaos_user):
    """
    ChaosOrchestrator.redis_hard_down() prevents usage recording.
    After context exit, Redis is restored to normal.
    """
    failing_redis = FailingRedis()
    orchestrator = ChaosOrchestrator(redis=failing_redis, session=db_session)
    uid = chaos_user.id
    svc = UsageMeteringService(failing_redis)

    async with orchestrator.redis_hard_down():
        with pytest.raises(ConnectionError):
            await svc.record(uid, api_calls=1)

    # After context, Redis is healthy
    await svc.record(uid, api_calls=1)
    usage = await svc.get_today(uid)
    assert usage["api_calls"] == 1.0


async def test_chaos_orchestrator_db_commit_fails(db_session, chaos_user):
    """
    ChaosOrchestrator.db_commit_fails() causes subscription transition commit to fail.
    After rollback, a fresh user verifies that commit functionality is restored.

    We use a new user for the recovery step because rollback removes chaos_user
    from the DB (same savepoint) and expire_all() leaves the ORM object in a state
    where re-adding it without expunge produces stale subscription_status reads.
    """
    from app.db.models.user import User as _User

    redis = FailingRedis()
    orchestrator = ChaosOrchestrator(redis=redis, session=db_session)

    async with orchestrator.db_commit_fails(after=0):
        svc = SubscriptionService(db_session)
        with pytest.raises(RuntimeError, match="CHAOS"):
            await svc.transition(chaos_user.id, SubscriptionStatus.TRIAL)

    await db_session.rollback()

    # Fresh user — no stale ORM state to worry about.
    recovery_user = _User(
        id=uuid.uuid4(),
        email=f"recovery_{uuid.uuid4().hex[:8]}@test.internal",
        hashed_password="$2b$12$fakehashforchaostesting000",
        is_active=True,
        is_verified=True,
        plan_tier="FREE",
        subscription_status="free",
    )
    db_session.add(recovery_user)
    await db_session.flush()

    svc = SubscriptionService(db_session)
    await svc.transition(recovery_user.id, SubscriptionStatus.TRIAL, reason="recovery_ok")
    status = await svc.get_status(recovery_user.id)
    assert status == SubscriptionStatus.TRIAL


async def test_both_hard_down_all_writes_fail(db_session, chaos_user):
    """
    ChaosOrchestrator.both_hard_down(): both Redis and DB fail simultaneously.
    No writes should succeed.  No invariants should be violated.
    """
    failing_redis = FailingRedis()
    orchestrator = ChaosOrchestrator(redis=failing_redis, session=db_session)
    uid = chaos_user.id

    redis_svc = UsageMeteringService(failing_redis)
    db_svc = SubscriptionService(db_session)

    async with orchestrator.both_hard_down():
        with pytest.raises((ConnectionError, RuntimeError)):
            await redis_svc.record(uid, api_calls=1)

        with pytest.raises((ConnectionError, RuntimeError)):
            await db_svc.transition(uid, SubscriptionStatus.TRIAL)

    suite = FinancialInvariantSuite()
    violations = await suite.check_all(db_session, stuck_lock_max_age_hours=24.0)
    assert not violations, f"Invariant violations after both-down: {violations}"

"""
Concurrent Billing Race Condition Tests
========================================
Tests the billing system's correctness guarantees under concurrent-like
access patterns, simulating the race conditions that would arise in production.

Architecture note: SQLAlchemy AsyncSession is not safe for concurrent coroutines
sharing the same session object.  These tests use sequential simulation:
  - Call A executes fully, then call B — testing state machine semantics
  - For true DB-level concurrency (two real connections racing on a UNIQUE
    constraint), the relevant code path is exercised via inject_commit_failure
    which directly tests the IntegrityError recovery branch in IdempotencyService.

All tests assert the FINANCIAL OUTCOME of race conditions, not the order of
execution.  The invariant suite validates correctness after each scenario.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import insert, select

from app.billing.constants import SubscriptionStatus
from app.billing.idempotency import (
    ConcurrentRequest,
    DuplicateRequest,
    IdempotencyService,
)
from app.billing.models import IdempotencyKey
from app.billing.subscription import InvalidTransition, SubscriptionService
from app.billing.usage_meter import UsageMeteringService
from tests.chaos.financial_invariants import FinancialInvariantSuite
from tests.fakes import FakeRedis


# ── Idempotency race conditions ───────────────────────────────────────────────

async def test_second_lock_on_same_key_raises_concurrent(db_session, chaos_user):
    """
    Sequence: A locks key → B tries to lock same key → ConcurrentRequest.
    This is the happy path for race detection.
    """
    key = f"race_{uuid.uuid4().hex}"
    svc = IdempotencyService(db_session)

    await svc.lock(key, user_id=chaos_user.id)

    with pytest.raises(ConcurrentRequest) as exc_info:
        await svc.lock(key, user_id=chaos_user.id)

    assert exc_info.value.key == key


async def test_lock_after_complete_returns_duplicate(db_session, chaos_user):
    """
    Sequence: A locks → A completes → B tries to lock → DuplicateRequest.
    B should receive the cached response without re-executing the operation.
    """
    key = f"dup_race_{uuid.uuid4().hex}"
    svc = IdempotencyService(db_session)

    await svc.lock(key, user_id=chaos_user.id)
    await svc.complete(key, {"charged": True, "amount": 999}, status_code=201)

    with pytest.raises(DuplicateRequest) as exc_info:
        await svc.lock(key, user_id=chaos_user.id)

    dr = exc_info.value
    assert dr.status_code == 201
    assert json.loads(dr.response_payload) == {"charged": True, "amount": 999}


async def test_10_sequential_locks_all_raise_concurrent(db_session, chaos_user):
    """
    Once a key is locked, every subsequent lock attempt (simulating 10 concurrent
    clients) raises ConcurrentRequest.  None of them succeed.
    """
    key = f"multi_lock_{uuid.uuid4().hex}"
    svc = IdempotencyService(db_session)

    await svc.lock(key, user_id=chaos_user.id)

    concurrent_count = 0
    for _ in range(10):
        try:
            await svc.lock(key, user_id=chaos_user.id)
        except ConcurrentRequest:
            concurrent_count += 1

    assert concurrent_count == 10, "Every concurrent lock attempt must raise ConcurrentRequest"


async def test_complete_then_10_retries_all_get_cached_response(db_session, chaos_user):
    """
    After completion, 10 retry attempts all receive the cached payload.
    This validates that the deduplication layer works consistently under
    repeated retries (models a client retrying due to network uncertainty).
    """
    key = f"cached_{uuid.uuid4().hex}"
    svc = IdempotencyService(db_session)

    await svc.lock(key, user_id=chaos_user.id)
    await svc.complete(key, {"transaction_id": "txn_abc123"}, status_code=200)

    for i in range(10):
        with pytest.raises(DuplicateRequest) as exc_info:
            await svc.lock(key, user_id=chaos_user.id)

        payload = json.loads(exc_info.value.response_payload)
        assert payload == {"transaction_id": "txn_abc123"}, \
            f"Retry {i}: expected cached payload, got {payload}"


async def test_integrity_error_recovery_path(db_session, chaos_user):
    """
    Simulates the UNIQUE constraint race: manually insert a locked row, then
    call lock() which hits the IntegrityError recovery branch.

    This directly tests the except IntegrityError → rollback → re-select path
    in IdempotencyService.lock().
    """
    key = f"integrity_{uuid.uuid4().hex}"
    from datetime import timedelta

    # Manually insert a 'locked' row bypassing the service (simulates another
    # process winning the race between our SELECT and INSERT)
    await db_session.execute(
        insert(IdempotencyKey).values(
            idempotency_key=key,
            user_id=chaos_user.id,
            status="locked",
            expires_at=datetime.now(timezone.utc) + timedelta(days=1),
        )
    )
    await db_session.flush()

    svc = IdempotencyService(db_session)
    with pytest.raises(ConcurrentRequest):
        await svc.lock(key, user_id=chaos_user.id)


# ── Usage recording under concurrent load ────────────────────────────────────

async def test_sequential_usage_accumulates_correctly(failing_redis):
    """
    10 sequential record() calls accumulate to exactly 10 api_calls.
    Validates that atomic Redis increments don't lose counts.
    """
    uid = uuid.uuid4()
    svc = UsageMeteringService(failing_redis)

    for _ in range(10):
        await svc.record(uid, api_calls=1)

    usage = await svc.get_today(uid)
    assert usage["api_calls"] == 10.0


async def test_mixed_api_call_counts_accumulate(failing_redis):
    """Different api_call values accumulate to the correct total."""
    uid = uuid.uuid4()
    svc = UsageMeteringService(failing_redis)

    amounts = [1, 3, 5, 2, 4]
    for amount in amounts:
        await svc.record(uid, api_calls=amount)

    usage = await svc.get_today(uid)
    assert usage["api_calls"] == float(sum(amounts))


async def test_day_and_month_counters_both_increment(failing_redis):
    """Every record() call increments both the daily and monthly counters."""
    uid = uuid.uuid4()
    svc = UsageMeteringService(failing_redis)

    for _ in range(5):
        await svc.record(uid, api_calls=2)

    today = await svc.get_today(uid)
    month = await svc.get_month(uid)

    assert today["api_calls"] == 10.0
    assert month["api_calls"] == 10.0


async def test_two_users_do_not_interfere(failing_redis):
    """Separate user IDs have completely independent usage counters."""
    uid_a = uuid.uuid4()
    uid_b = uuid.uuid4()
    svc = UsageMeteringService(failing_redis)

    for _ in range(3):
        await svc.record(uid_a, api_calls=10)
    for _ in range(7):
        await svc.record(uid_b, api_calls=1)

    usage_a = await svc.get_today(uid_a)
    usage_b = await svc.get_today(uid_b)

    assert usage_a["api_calls"] == 30.0
    assert usage_b["api_calls"] == 7.0


# ── Subscription state machine under repeated transitions ─────────────────────

async def test_all_valid_transitions_execute_sequentially(db_session, chaos_user):
    """
    Walk a valid transition path: free → trial → active → past_due → active → canceled.
    Each step must succeed and leave a correct audit log entry.
    """
    svc = SubscriptionService(db_session)

    path = [
        SubscriptionStatus.TRIAL,
        SubscriptionStatus.ACTIVE,
        SubscriptionStatus.PAST_DUE,
        SubscriptionStatus.ACTIVE,
        SubscriptionStatus.CANCELED,
    ]
    for target in path:
        await svc.transition(chaos_user.id, target, reason=f"→{target.value}")

    history = await svc.history(chaos_user.id)
    assert len(history) == len(path)

    final = await svc.get_status(chaos_user.id)
    assert final == SubscriptionStatus.CANCELED


async def test_all_invalid_transitions_rejected(db_session, chaos_user):
    """
    From 'free', all transitions except trial and active are invalid.
    Verified invalid transitions must raise InvalidTransition without side effects.
    """
    svc = SubscriptionService(db_session)

    invalid_targets = [
        SubscriptionStatus.PAST_DUE,
        SubscriptionStatus.CANCELED,
        SubscriptionStatus.SUSPENDED,
    ]
    for target in invalid_targets:
        with pytest.raises(InvalidTransition):
            await svc.transition(chaos_user.id, target)

    # User still free, no audit log
    status = await svc.get_status(chaos_user.id)
    assert status == SubscriptionStatus.FREE

    history = await svc.history(chaos_user.id)
    assert len(history) == 0


async def test_transition_to_same_status_is_rejected(db_session, chaos_user):
    """
    Transitioning to the current status is not a valid edge in VALID_TRANSITIONS.
    Should raise InvalidTransition (not silently succeed).
    """
    svc = SubscriptionService(db_session)

    with pytest.raises(InvalidTransition):
        await svc.transition(chaos_user.id, SubscriptionStatus.FREE)


# ── Invariants after race scenarios ──────────────────────────────────────────

async def test_invariants_clean_after_concurrent_lock_attempts(db_session, chaos_user, invariants):
    """
    After a lock race (first wins, rest raise ConcurrentRequest), all invariants hold.
    """
    key = f"inv_race_{uuid.uuid4().hex}"
    svc = IdempotencyService(db_session)

    await svc.lock(key, user_id=chaos_user.id)
    for _ in range(5):
        try:
            await svc.lock(key, user_id=chaos_user.id)
        except ConcurrentRequest:
            pass

    # Allow stuck lock age threshold to be large (lock IS legitimately locked here)
    violations = await invariants.check_all(db_session, stuck_lock_max_age_hours=24.0)
    assert not violations, f"Unexpected invariant violations: {violations}"


async def test_invariants_clean_after_full_idempotency_lifecycle(db_session, chaos_user, invariants):
    """
    After lock → complete → duplicate storm, I1 invariant (no duplicate completions)
    must hold — the key appears exactly once in complete status.
    """
    key = f"lifecycle_{uuid.uuid4().hex}"
    svc = IdempotencyService(db_session)

    await svc.lock(key, user_id=chaos_user.id)
    await svc.complete(key, {"ok": True})

    for _ in range(10):
        try:
            await svc.lock(key, user_id=chaos_user.id)
        except DuplicateRequest:
            pass

    violations = await invariants.check_all(db_session, stuck_lock_max_age_hours=24.0)
    assert not violations, f"Invariant violations after lifecycle: {violations}"

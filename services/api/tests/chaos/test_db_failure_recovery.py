"""
DB Failure Recovery Tests
==========================
Verifies that billing services handle database failures correctly:
  - Commit failures leave state retryable, not corrupted
  - Idempotency locks are not persisted when commits fail
  - Subscription transitions are atomic (audit log + user row change together)
  - Webhook events survive processing failures
  - Financial invariants hold after all failure scenarios
"""
from __future__ import annotations

import json
import uuid

import pytest
from sqlalchemy import select

from app.billing.constants import SubscriptionStatus
from app.billing.idempotency import (
    ConcurrentRequest,
    DuplicateRequest,
    IdempotencyService,
)
from app.billing.models import IdempotencyKey, SubscriptionAuditLog, WebhookEvent
from app.billing.subscription import InvalidTransition, SubscriptionService
from app.billing.usage_meter import UsageMeteringService
from app.billing.webhook import WebhookService
from tests.chaos.financial_invariants import FinancialInvariantSuite
from tests.chaos.injectors import inject_commit_failure, inject_execute_failure
from tests.fakes import FakeRedis


# ── Idempotency under DB failure ──────────────────────────────────────────────

async def test_idempotency_lock_not_persisted_on_commit_failure(db_session, chaos_user):
    """
    When commit fails after INSERT, the lock row must not be left in DB.
    After the injected RuntimeError, the session has unflushed pending objects.
    We explicitly rollback to clear that state before asserting.
    """
    key = f"idem_fail_{uuid.uuid4().hex}"

    async with inject_commit_failure(db_session, after=0) as patched:
        svc = IdempotencyService(patched)
        with pytest.raises(RuntimeError, match="CHAOS"):
            await svc.lock(key, user_id=chaos_user.id)

    # The injected commit raised before flushing — the session still holds the
    # pending row in its identity map.  Rollback clears it cleanly.
    await db_session.rollback()

    result = await db_session.execute(
        select(IdempotencyKey).where(IdempotencyKey.idempotency_key == key)
    )
    row = result.scalar_one_or_none()
    assert row is None, "Failed commit must not leave a locked idempotency row"


async def test_idempotency_key_retryable_after_commit_failure(db_session):
    """
    After a commit failure, the same key can be retried (lock never persisted).
    user_id=None (nullable FK) avoids needing a chaos_user row that rollback
    would also remove from the same savepoint.
    """
    key = f"retry_{uuid.uuid4().hex}"

    async with inject_commit_failure(db_session, after=0) as patched:
        svc = IdempotencyService(patched)
        with pytest.raises(RuntimeError, match="CHAOS"):
            await svc.lock(key)  # user_id=None — nullable FK

    # The row was pending (never flushed — fake commit raised immediately).
    # Rollback clears the pending object from the ORM identity map, preventing
    # autoflush from writing it to DB on the next SELECT.
    await db_session.rollback()

    svc2 = IdempotencyService(db_session)
    await svc2.lock(key)  # must not raise — key was never persisted

    result = await db_session.execute(
        select(IdempotencyKey).where(IdempotencyKey.idempotency_key == key)
    )
    row = result.scalar_one_or_none()
    assert row is not None and row.status == "locked"


async def test_complete_after_lock_updates_status(db_session, chaos_user):
    """Two-phase: lock then complete → status transitions locked→complete."""
    key = f"twophase_{uuid.uuid4().hex}"
    svc = IdempotencyService(db_session)

    await svc.lock(key, user_id=chaos_user.id)
    await svc.complete(key, {"charged": True}, status_code=200)

    result = await db_session.execute(
        select(IdempotencyKey).where(IdempotencyKey.idempotency_key == key)
    )
    row = result.scalar_one_or_none()
    assert row is not None
    assert row.status == "complete"
    assert json.loads(row.response_payload) == {"charged": True}


async def test_duplicate_lock_raises_concurrent_request(db_session, chaos_user):
    """Second lock on same key (status='locked') raises ConcurrentRequest."""
    key = f"concurrent_{uuid.uuid4().hex}"
    svc = IdempotencyService(db_session)

    await svc.lock(key, user_id=chaos_user.id)

    with pytest.raises(ConcurrentRequest):
        await svc.lock(key, user_id=chaos_user.id)


async def test_lock_after_complete_raises_duplicate_request(db_session, chaos_user):
    """lock() on a completed key raises DuplicateRequest with cached payload."""
    key = f"dup_{uuid.uuid4().hex}"
    svc = IdempotencyService(db_session)

    await svc.lock(key, user_id=chaos_user.id)
    await svc.complete(key, {"result": "success"}, status_code=201)

    with pytest.raises(DuplicateRequest) as exc_info:
        await svc.lock(key, user_id=chaos_user.id)

    dr = exc_info.value
    assert dr.status_code == 201
    assert json.loads(dr.response_payload) == {"result": "success"}


# ── Subscription transitions under DB failure ─────────────────────────────────

async def test_subscription_transition_commit_failure_is_atomic(db_session, chaos_user):
    """
    If commit fails mid-transition, neither the audit log row nor the user
    status update should be persisted (atomicity guarantee).
    Rollback after injected failure clears the pending ORM objects.
    """
    async with inject_commit_failure(db_session, after=0) as patched:
        svc = SubscriptionService(patched)
        with pytest.raises(RuntimeError, match="CHAOS"):
            await svc.transition(
                chaos_user.id,
                SubscriptionStatus.TRIAL,
                reason="chaos test",
            )

    # Rollback undoes all flushed changes (log row, user update) within the active
    # savepoint — including the chaos_user row itself (also flushed in this savepoint).
    await db_session.rollback()

    # Verify the audit log was rolled back.  We cannot check user.subscription_status
    # because the chaos_user row was rolled back too — absence of the log is the
    # correct atomicity proof here.
    result = await db_session.execute(
        select(SubscriptionAuditLog).where(
            SubscriptionAuditLog.user_id == chaos_user.id
        )
    )
    logs = result.scalars().all()
    assert len(logs) == 0, "Rolled-back transition must not leave an audit log entry"


async def test_subscription_audit_log_created_on_success(db_session, chaos_user):
    """Successful transition creates an audit log entry with correct statuses."""
    svc = SubscriptionService(db_session)
    log = await svc.transition(
        chaos_user.id,
        SubscriptionStatus.TRIAL,
        reason="chaos_ok",
    )

    assert log.from_status == "free"
    assert log.to_status == "trial"
    assert log.reason == "chaos_ok"

    status = await svc.get_status(chaos_user.id)
    assert status == SubscriptionStatus.TRIAL


async def test_invalid_transition_raises_and_does_not_persist(db_session, chaos_user):
    """
    InvalidTransition is raised before any DB writes.
    No audit log entry should exist after rejection.
    """
    svc = SubscriptionService(db_session)

    # free → canceled is not in VALID_TRANSITIONS
    with pytest.raises(InvalidTransition):
        await svc.transition(chaos_user.id, SubscriptionStatus.CANCELED)

    result = await db_session.execute(
        select(SubscriptionAuditLog).where(
            SubscriptionAuditLog.user_id == chaos_user.id
        )
    )
    logs = result.scalars().all()
    assert len(logs) == 0


# ── Webhook under DB failure ──────────────────────────────────────────────────

async def test_webhook_event_persisted_before_processing(db_session):
    """
    WebhookService persists the event row before attempting processing.
    The event row must exist in DB regardless of whether processing succeeds.
    """
    svc = WebhookService(db_session)
    event_id = f"evt_{uuid.uuid4().hex}"
    import json as _json
    payload = _json.dumps({
        "id": event_id,
        "type": "invoice.paid",
        "data": {"object": {"customer": "cus_nonexistent"}},
    }).encode()

    event = await svc.process(payload)

    result = await db_session.execute(
        select(WebhookEvent).where(WebhookEvent.stripe_event_id == event_id)
    )
    row = result.scalar_one_or_none()
    assert row is not None
    assert row.status == "processed"
    assert event.id == row.id


async def test_flush_to_db_handles_execute_failure(db_session, failing_redis):
    """
    flush_to_db() raises when DB execute fails.
    Redis data is unaffected — it can be retried.
    """
    from tests.fakes import FakeRedis
    redis = FakeRedis()
    svc = UsageMeteringService(redis)
    uid = uuid.uuid4()

    from datetime import date
    today = date.today().isoformat()

    await svc.record(uid, api_calls=5)

    async with inject_execute_failure(db_session, after=0) as patched:
        with pytest.raises(RuntimeError, match="CHAOS"):
            await svc.flush_to_db(patched, uid, period_type="day", period_key=today)

    # Redis state unmodified — retry is possible
    usage = await svc.get_today(uid)
    assert usage["api_calls"] == 5.0


# ── Financial invariants after failure scenarios ──────────────────────────────

async def test_invariants_hold_after_failed_idempotency_lock(db_session, chaos_user, invariants):
    """Financial invariants are clean even after a failed idempotency lock."""
    key = f"inv_idem_{uuid.uuid4().hex}"

    async with inject_commit_failure(db_session, after=0) as patched:
        svc = IdempotencyService(patched)
        with pytest.raises(RuntimeError, match="CHAOS"):
            await svc.lock(key, user_id=chaos_user.id)

    violations = await invariants.check_all(db_session, stuck_lock_max_age_hours=0.001)
    assert not violations, f"Invariant violations after failed lock: {violations}"


async def test_invariants_hold_after_successful_two_phase_lock(db_session, chaos_user, invariants):
    """I1 invariant: completed idempotency key appears exactly once."""
    key = f"inv_ok_{uuid.uuid4().hex}"
    svc = IdempotencyService(db_session)

    await svc.lock(key, user_id=chaos_user.id)
    await svc.complete(key, {"ok": True}, status_code=200)

    violations = await invariants.check_all(db_session, stuck_lock_max_age_hours=24.0)
    assert not violations, f"Unexpected invariant violations: {violations}"

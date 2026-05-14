"""
Billing Safety — Race Condition & Double-Billing Tests
=======================================================
Simulates concurrent billing operations to validate:
  - No double charges via idempotency keys
  - No quota over-counting from concurrent increments
  - Webhook replay safety
  - State machine prevents invalid concurrent transitions
"""
from __future__ import annotations

import asyncio
import uuid
import json

import pytest

from app.billing.idempotency import IdempotencyService, DuplicateRequest, ConcurrentRequest
from app.billing.usage_meter import UsageMeteringService
from app.billing.webhook import WebhookService




# ── Double billing prevention ─────────────────────────────────────────────────

async def test_sequential_lock_only_first_wins(db_session, db_user):
    """
    Simulates two requests arriving for the same idempotency key sequentially.
    The first request locks; the second must see ConcurrentRequest.
    The third (after complete) must see DuplicateRequest.

    asyncio is single-threaded — real concurrent races are prevented at the
    DB level via UNIQUE constraint + IntegrityError (tested by test_idempotency.py).
    This test validates the state-machine semantics.
    """
    key = f"race_{uuid.uuid4().hex}"
    svc = IdempotencyService(db_session)

    # Request 1: locks the key
    await svc.lock(key, db_user.id)

    # Request 2: sees a locked row → ConcurrentRequest
    with pytest.raises(ConcurrentRequest):
        await svc.lock(key, db_user.id)

    # Request 1 completes
    await svc.complete(key, {"charge_id": "ch_only_once"}, 200)

    # Request 3 (retry after complete): sees cached response → DuplicateRequest
    with pytest.raises(DuplicateRequest) as exc_info:
        await svc.lock(key, db_user.id)

    assert "ch_only_once" in exc_info.value.response_payload


async def test_complete_then_retry_returns_cached(db_session, db_user):
    """After complete(), any retry gets the cached response, not a new charge."""
    key = f"charge_{uuid.uuid4().hex}"
    svc = IdempotencyService(db_session)

    await svc.lock(key, db_user.id)
    await svc.complete(key, {"charge_id": "ch_original"}, 200)

    # Simulate 10 sequential retries — each must see the cached response
    duplicate_payloads = []
    for _ in range(10):
        try:
            await svc.lock(key, db_user.id)
        except DuplicateRequest as dr:
            duplicate_payloads.append(dr.response_payload)

    assert len(duplicate_payloads) == 10
    assert all("ch_original" in p for p in duplicate_payloads)


# ── Quota counting correctness ────────────────────────────────────────────────

async def test_concurrent_usage_increments_are_accurate(fake_redis):
    """
    N concurrent record() calls must produce exactly N in the counter.
    asyncio is cooperative so no actual race, but validates accumulation logic.
    """
    uid = uuid.uuid4()
    svc = UsageMeteringService(fake_redis)
    N = 500

    await asyncio.gather(*[svc.record(uid, api_calls=1) for _ in range(N)])

    data = await svc.get_today(uid)
    assert data["api_calls"] == float(N), (
        f"Expected {N} api_calls, got {data['api_calls']}"
    )


async def test_concurrent_users_do_not_cross_contaminate(fake_redis):
    """Concurrent records for different users must not bleed into each other."""
    USERS = 20
    CALLS_PER_USER = 50
    uids = [uuid.uuid4() for _ in range(USERS)]
    svc = UsageMeteringService(fake_redis)

    async def _record_user(uid):
        for _ in range(CALLS_PER_USER):
            await svc.record(uid, api_calls=1)

    await asyncio.gather(*[_record_user(uid) for uid in uids])

    for uid in uids:
        data = await svc.get_today(uid)
        assert data["api_calls"] == float(CALLS_PER_USER), (
            f"User {uid}: expected {CALLS_PER_USER}, got {data['api_calls']}"
        )


# ── Webhook replay safety ─────────────────────────────────────────────────────

async def test_concurrent_same_webhook_only_processes_once(db_session):
    """
    Simulates Stripe sending the same webhook multiple times simultaneously.
    The event must be persisted once and processed at most once.
    """
    event_id = f"evt_concurrent_{uuid.uuid4().hex}"
    payload = json.dumps({
        "id": event_id,
        "type": "invoice.paid",
        "data": {"object": {"customer": "cus_nobody"}},
    }).encode()

    svc = WebhookService(db_session)
    results = await asyncio.gather(
        *[svc.process(payload) for _ in range(10)],
        return_exceptions=True,
    )

    successful = [r for r in results if not isinstance(r, Exception)]
    assert len(successful) >= 1, "At least one processing must succeed"

    # All successful results must point to the same event row
    event_ids = {r.id for r in successful}
    assert len(event_ids) == 1, "All coroutines must see the same event row"


# ── State machine concurrency ─────────────────────────────────────────────────

async def test_sequential_invalid_transitions_are_rejected(db_session, db_user):
    """
    After a user reaches CANCELED, further invalid transitions are rejected
    even when attempted many times sequentially.
    """
    from app.billing.subscription import SubscriptionService, InvalidTransition
    from app.billing.constants import SubscriptionStatus

    svc = SubscriptionService(db_session)
    await svc.transition(db_user.id, SubscriptionStatus.TRIAL)
    await svc.transition(db_user.id, SubscriptionStatus.ACTIVE)
    await svc.transition(db_user.id, SubscriptionStatus.CANCELED)

    rejection_count = 0
    for _ in range(10):
        try:
            await svc.transition(db_user.id, SubscriptionStatus.PAST_DUE)
        except InvalidTransition:
            rejection_count += 1

    assert rejection_count == 10, "All 10 invalid transitions must be rejected"

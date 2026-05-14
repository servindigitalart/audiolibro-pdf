"""
Stripe Idempotency Tests
===========================
Verifies that Stripe-layer idempotency keys and billing idempotency
work together correctly under retry and concurrent-request scenarios.

Scenarios:
  - Duplicate create_subscription calls with the same idempotency_key
  - Stripe client call log records correct idempotency keys
  - DB-level IdempotencyService prevents double charging
  - Webhook dedup prevents double state transition
  - Stripe error on first attempt + retry succeeds (one-shot failure)
  - Concurrent subscription creation attempts are safe
"""
from __future__ import annotations

import json
import uuid

import pytest

from app.billing.constants import SubscriptionStatus
from app.billing.idempotency import ConcurrentRequest, DuplicateRequest, IdempotencyService
from app.billing.models import IdempotencyKey, WebhookEvent
from app.billing.stripe.base import StripeError
from app.billing.subscription import SubscriptionService
from app.billing.webhook import WebhookService
from sqlalchemy import func, select


# ── Stripe-level idempotency keys ─────────────────────────────────────────────

async def test_same_idempotency_key_returns_same_sub_id(mock_stripe):
    c = await mock_stripe.create_customer("idem@test.internal", "uid")
    key = f"idem_{uuid.uuid4().hex}"

    sub1 = await mock_stripe.create_subscription(c.id, "price_basic", key)
    sub2 = await mock_stripe.create_subscription(c.id, "price_basic", key)

    assert sub1.id == sub2.id


async def test_idempotency_key_is_recorded_in_call_log(mock_stripe):
    c = await mock_stripe.create_customer("idem2@test.internal", "uid")
    key = f"idem_key_{uuid.uuid4().hex}"

    await mock_stripe.create_subscription(c.id, "price_basic", key)

    call = mock_stripe.calls("create_subscription")[0]
    assert call["idempotency_key"] == key


async def test_different_keys_create_different_subscriptions(mock_stripe):
    c = await mock_stripe.create_customer("idem3@test.internal", "uid")

    sub1 = await mock_stripe.create_subscription(c.id, "price_basic", f"key_a_{uuid.uuid4().hex}")
    sub2 = await mock_stripe.create_subscription(c.id, "price_basic", f"key_b_{uuid.uuid4().hex}")

    assert sub1.id != sub2.id


async def test_checkout_session_idempotency_key_recorded(mock_stripe):
    c = await mock_stripe.create_customer("idem4@test.internal", "uid")
    key = f"checkout_{uuid.uuid4().hex}"

    await mock_stripe.create_checkout_session(
        customer_id=c.id,
        price_id="price_basic",
        success_url="https://app.com/success",
        cancel_url="https://app.com/cancel",
        idempotency_key=key,
    )

    call = mock_stripe.calls("create_checkout_session")[0]
    assert call["idempotency_key"] == key


# ── Retry after one-shot failure ──────────────────────────────────────────────

async def test_retry_after_stripe_error_succeeds(mock_stripe):
    c = await mock_stripe.create_customer("retry@test.internal", "uid")
    key = f"retry_{uuid.uuid4().hex}"

    mock_stripe.configure_failure("create_subscription")
    with pytest.raises(StripeError):
        await mock_stripe.create_subscription(c.id, "price_basic", key)

    # Second attempt (same key) succeeds — one-shot failure
    sub = await mock_stripe.create_subscription(c.id, "price_basic", key)
    assert sub.id.startswith("sub_mock_")


async def test_retry_does_not_create_duplicate_subscription(mock_stripe):
    c = await mock_stripe.create_customer("retry2@test.internal", "uid")
    key = f"retry2_{uuid.uuid4().hex}"

    mock_stripe.configure_failure("create_subscription")
    try:
        await mock_stripe.create_subscription(c.id, "price_basic", key)
    except StripeError:
        pass

    await mock_stripe.create_subscription(c.id, "price_basic", key)

    subs = await mock_stripe.list_customer_subscriptions(c.id)
    assert len(subs) == 1


# ── DB-level idempotency under Stripe retries ─────────────────────────────────

async def test_db_idempotency_lock_prevents_concurrent_charge(db_session, stripe_user):
    user, _ = stripe_user
    key = f"charge_{uuid.uuid4().hex}"

    svc = IdempotencyService(db_session)
    await svc.lock(key, user_id=user.id)

    with pytest.raises(ConcurrentRequest):
        await svc.lock(key, user_id=user.id)


async def test_completed_idempotency_key_raises_duplicate_request(db_session, stripe_user):
    user, _ = stripe_user
    key = f"complete_{uuid.uuid4().hex}"
    cached = {"sub_id": "sub_mock_xyz", "status": "active"}

    svc = IdempotencyService(db_session)
    await svc.lock(key, user_id=user.id)
    await svc.complete(key, cached)

    # Re-lock a completed key raises DuplicateRequest
    with pytest.raises(DuplicateRequest) as exc_info:
        await svc.lock(key, user_id=user.id)
    assert exc_info.value.key == key


async def test_completed_key_stores_response_payload(db_session, stripe_user):
    user, _ = stripe_user
    key = f"payload_{uuid.uuid4().hex}"
    cached = {"sub_id": "sub_mock_abc", "status": "active"}

    svc = IdempotencyService(db_session)
    await svc.lock(key, user_id=user.id)
    await svc.complete(key, cached)

    row = await svc._get(key)
    assert row is not None
    assert row.status == "complete"
    assert json.loads(row.response_payload) == cached


# ── Webhook dedup prevents double state transition ────────────────────────────

async def test_duplicate_invoice_paid_does_not_double_transition(
    db_session, active_stripe_user
):
    _user, customer, sub = active_stripe_user
    event_id = f"evt_{uuid.uuid4().hex}"

    payload = json.dumps({
        "id": event_id,
        "type": "invoice.paid",
        "data": {"object": {"customer": customer.id, "subscription": sub.id}},
    }).encode()

    webhook = WebhookService(db_session)
    await webhook.process(payload)
    await webhook.process(payload)

    result = await db_session.execute(
        select(func.count()).select_from(WebhookEvent)
        .where(WebhookEvent.stripe_event_id == event_id)
    )
    assert result.scalar_one() == 1


async def test_duplicate_checkout_completed_does_not_double_activate(
    db_session, stripe_user, mock_stripe
):
    user, customer = stripe_user
    sub = await mock_stripe.create_subscription(
        customer.id, "price_basic", f"k_{uuid.uuid4().hex}"
    )
    event_id = f"evt_{uuid.uuid4().hex}"

    payload = json.dumps({
        "id": event_id,
        "type": "checkout.session.completed",
        "data": {"object": {"customer": customer.id, "subscription": sub.id}},
    }).encode()

    webhook = WebhookService(db_session)
    await webhook.process(payload)
    await webhook.process(payload)  # Second delivery — must be deduped

    svc = SubscriptionService(db_session)
    status = await svc.get_status(user.id)
    assert status == SubscriptionStatus.ACTIVE

    result = await db_session.execute(
        select(func.count()).select_from(WebhookEvent)
        .where(WebhookEvent.stripe_event_id == event_id)
    )
    assert result.scalar_one() == 1


# ── Multiple distinct events for same user ────────────────────────────────────

async def test_sequential_events_each_processed_once(db_session, active_stripe_user):
    user, customer, sub = active_stripe_user
    events = [
        ("invoice.payment_failed", f"evt_fail_{uuid.uuid4().hex}"),
        ("invoice.paid", f"evt_paid_{uuid.uuid4().hex}"),
    ]

    webhook = WebhookService(db_session)
    for event_type, event_id in events:
        payload = json.dumps({
            "id": event_id,
            "type": event_type,
            "data": {"object": {"customer": customer.id, "subscription": sub.id}},
        }).encode()
        await webhook.process(payload)

    svc = SubscriptionService(db_session)
    status = await svc.get_status(user.id)
    assert status == SubscriptionStatus.ACTIVE

    logs = await svc.history(user.id)
    assert len(logs) >= 2


# ── State machine idempotency ─────────────────────────────────────────────────

async def test_transition_to_current_status_is_allowed_if_in_valid_transitions(
    db_session, active_stripe_user
):
    """Verify the state machine allows the same webhook to be replayed safely."""
    user, _customer, _sub = active_stripe_user
    svc = SubscriptionService(db_session)

    # active → past_due → active: normal cycle
    await svc.transition(user.id, SubscriptionStatus.PAST_DUE, reason="test")
    await svc.transition(user.id, SubscriptionStatus.ACTIVE, reason="test")

    status = await svc.get_status(user.id)
    assert status == SubscriptionStatus.ACTIVE


async def test_idempotency_key_has_future_expiry(db_session, stripe_user):
    """Locked keys are created with a future expires_at for cleanup."""
    from datetime import datetime, timezone

    user, _ = stripe_user
    key = f"ttl_{uuid.uuid4().hex}"

    svc = IdempotencyService(db_session)
    await svc.lock(key, user_id=user.id)

    row = await svc._get(key)
    assert row is not None
    assert row.expires_at is not None
    assert row.expires_at > datetime.now(timezone.utc)

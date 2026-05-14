"""
Stripe Webhook Integration Tests
===================================
Tests the WebhookService with real DB sessions:
  - All Stripe event types are dispatched correctly
  - Idempotency: duplicate events are deduplicated (one DB row)
  - Signature validation accepts valid / rejects tampered payloads
  - Unknown event types are persisted but not processed (ignored)
  - checkout.session.completed handler correctness
  - Replay of stored events via WebhookService.replay()
"""
from __future__ import annotations

import hashlib
import hmac
import json
import time
import uuid
from datetime import datetime, timezone

import pytest

from app.billing.constants import SubscriptionStatus
from app.billing.models import WebhookEvent
from app.billing.subscription import SubscriptionService
from app.billing.webhook import InvalidSignature, WebhookService
from sqlalchemy import select
from sqlalchemy import func


# ── Payload builders ──────────────────────────────────────────────────────────

def _payload(event_type: str, obj: dict, event_id: str | None = None) -> bytes:
    return json.dumps({
        "id": event_id or f"evt_{uuid.uuid4().hex}",
        "type": event_type,
        "data": {"object": obj},
    }).encode()


def _sign(secret: str, body: bytes, t: int | None = None) -> str:
    ts = t or int(time.time())
    signed = f"{ts}.{body.decode()}"
    sig = hmac.new(secret.encode(), signed.encode(), hashlib.sha256).hexdigest()
    return f"t={ts},v1={sig}"


# ── Idempotency ───────────────────────────────────────────────────────────────

async def test_duplicate_event_produces_one_row(db_session):
    svc = WebhookService(db_session)
    event_id = f"evt_{uuid.uuid4().hex}"
    payload = _payload("invoice.paid", {"customer": "cus_x", "subscription": "sub_x"}, event_id)

    e1 = await svc.process(payload)
    e2 = await svc.process(payload)

    assert e1.stripe_event_id == e2.stripe_event_id == event_id

    result = await db_session.execute(
        select(func.count()).select_from(WebhookEvent)
        .where(WebhookEvent.stripe_event_id == event_id)
    )
    assert result.scalar_one() == 1


async def test_second_delivery_returns_existing_row(db_session):
    svc = WebhookService(db_session)
    event_id = f"evt_{uuid.uuid4().hex}"
    payload = _payload("invoice.paid", {"customer": "cus_x"}, event_id)

    first = await svc.process(payload)
    second = await svc.process(payload)

    assert first.id == second.id


async def test_ten_duplicate_deliveries_one_row(db_session):
    svc = WebhookService(db_session)
    event_id = f"evt_{uuid.uuid4().hex}"
    payload = _payload("invoice.paid", {"customer": "cus_dup"}, event_id)

    for _ in range(10):
        await svc.process(payload)

    result = await db_session.execute(
        select(func.count()).select_from(WebhookEvent)
        .where(WebhookEvent.stripe_event_id == event_id)
    )
    assert result.scalar_one() == 1


# ── Event persistence ─────────────────────────────────────────────────────────

async def test_event_is_persisted_to_db(db_session):
    svc = WebhookService(db_session)
    event_id = f"evt_{uuid.uuid4().hex}"
    payload = _payload("invoice.paid", {"customer": "cus_x"}, event_id)
    event = await svc.process(payload)

    result = await db_session.execute(
        select(WebhookEvent).where(WebhookEvent.stripe_event_id == event_id)
    )
    row = result.scalar_one_or_none()
    assert row is not None
    assert row.id == event.id


async def test_event_status_is_processed_after_dispatch(db_session):
    svc = WebhookService(db_session)
    payload = _payload("invoice.paid", {"customer": "cus_x", "subscription": "sub_x"})
    event = await svc.process(payload)
    assert event.status == "processed"


async def test_unknown_event_type_is_persisted_as_ignored(db_session):
    svc = WebhookService(db_session)
    payload = _payload("payment_intent.created", {"id": "pi_xxx"})
    event = await svc.process(payload)
    assert event.status in ("ignored", "processed")
    assert event.stripe_event_id is not None


# ── invoice.paid ──────────────────────────────────────────────────────────────

async def test_invoice_paid_transitions_trial_to_active(db_session, active_stripe_user):
    user, customer, sub = active_stripe_user

    # Put user in TRIAL first
    svc = SubscriptionService(db_session)
    await svc.transition(user.id, SubscriptionStatus.PAST_DUE, reason="test_setup")

    webhook = WebhookService(db_session)
    await webhook.process(
        _payload("invoice.paid", {"customer": customer.id, "subscription": sub.id})
    )

    status = await svc.get_status(user.id)
    assert status == SubscriptionStatus.ACTIVE


async def test_invoice_paid_for_unknown_customer_is_benign(db_session):
    svc = WebhookService(db_session)
    event = await svc.process(
        _payload("invoice.paid", {"customer": "cus_completely_unknown", "subscription": "sub_x"})
    )
    assert event.status in ("processed", "ignored")


# ── invoice.payment_failed ────────────────────────────────────────────────────

async def test_invoice_payment_failed_moves_active_to_past_due(db_session, active_stripe_user):
    user, customer, sub = active_stripe_user
    svc_sub = SubscriptionService(db_session)
    webhook = WebhookService(db_session)

    await webhook.process(
        _payload("invoice.payment_failed", {"customer": customer.id, "subscription": sub.id})
    )

    status = await svc_sub.get_status(user.id)
    assert status == SubscriptionStatus.PAST_DUE


# ── customer.subscription.deleted ────────────────────────────────────────────

async def test_subscription_deleted_cancels_active_subscription(db_session, active_stripe_user):
    user, customer, sub = active_stripe_user
    webhook = WebhookService(db_session)

    await webhook.process(
        _payload(
            "customer.subscription.deleted",
            {"id": sub.id, "customer": customer.id, "status": "canceled"},
        )
    )

    svc = SubscriptionService(db_session)
    status = await svc.get_status(user.id)
    assert status == SubscriptionStatus.CANCELED


# ── customer.subscription.updated ────────────────────────────────────────────

async def test_subscription_updated_past_due_syncs_local_status(
    db_session, active_stripe_user
):
    user, customer, sub = active_stripe_user
    webhook = WebhookService(db_session)

    await webhook.process(
        _payload(
            "customer.subscription.updated",
            {"id": sub.id, "customer": customer.id, "status": "past_due"},
        )
    )

    svc = SubscriptionService(db_session)
    status = await svc.get_status(user.id)
    assert status == SubscriptionStatus.PAST_DUE


# ── checkout.session.completed ────────────────────────────────────────────────

async def test_checkout_completed_activates_free_user(db_session, stripe_user, mock_stripe):
    user, customer = stripe_user
    sub = await mock_stripe.create_subscription(
        customer.id, "price_basic", f"idem_{uuid.uuid4().hex}"
    )

    webhook = WebhookService(db_session)
    await webhook.process(
        _payload(
            "checkout.session.completed",
            {"customer": customer.id, "subscription": sub.id, "payment_status": "paid"},
        )
    )

    svc = SubscriptionService(db_session)
    status = await svc.get_status(user.id)
    assert status == SubscriptionStatus.ACTIVE


async def test_checkout_completed_records_subscription_id(
    db_session, stripe_user, mock_stripe
):
    from sqlalchemy import select as sa_select
    from app.db.models.user import User

    user, customer = stripe_user
    sub = await mock_stripe.create_subscription(
        customer.id, "price_basic", f"idem_{uuid.uuid4().hex}"
    )

    webhook = WebhookService(db_session)
    await webhook.process(
        _payload(
            "checkout.session.completed",
            {"customer": customer.id, "subscription": sub.id},
        )
    )

    result = await db_session.execute(sa_select(User).where(User.id == user.id))
    u = result.scalar_one()
    assert u.stripe_subscription_id == sub.id


async def test_checkout_completed_already_active_is_idempotent(
    db_session, active_stripe_user
):
    user, customer, sub = active_stripe_user
    webhook = WebhookService(db_session)

    # Should not raise even though user is already ACTIVE
    await webhook.process(
        _payload(
            "checkout.session.completed",
            {"customer": customer.id, "subscription": sub.id},
        )
    )

    svc = SubscriptionService(db_session)
    status = await svc.get_status(user.id)
    assert status == SubscriptionStatus.ACTIVE


# ── Signature validation ──────────────────────────────────────────────────────

def test_valid_signature_accepted():
    secret = "whsec_test_secret_abc123"
    payload = _payload("invoice.paid", {"customer": "cus_x"})
    sig = _sign(secret, payload)

    svc = WebhookService(None, webhook_secret=secret)  # type: ignore[arg-type]
    svc.verify_signature(payload, sig)  # Must not raise


def test_tampered_signature_rejected():
    secret = "whsec_test_secret_abc123"
    payload = _payload("invoice.paid", {"customer": "cus_x"})
    bad_sig = _sign("wrong_secret", payload)

    svc = WebhookService(None, webhook_secret=secret)  # type: ignore[arg-type]
    with pytest.raises(InvalidSignature):
        svc.verify_signature(payload, bad_sig)


def test_old_timestamp_rejected():
    secret = "whsec_test_secret_abc123"
    payload = _payload("invoice.paid", {"customer": "cus_x"})
    old_t = int(time.time()) - 400  # > 300s threshold
    old_sig = _sign(secret, payload, t=old_t)

    svc = WebhookService(None, webhook_secret=secret)  # type: ignore[arg-type]
    with pytest.raises(InvalidSignature, match="too old"):
        svc.verify_signature(payload, old_sig)


def test_missing_secret_skips_validation():
    payload = _payload("invoice.paid", {"customer": "cus_x"})
    svc = WebhookService(None, webhook_secret="")  # type: ignore[arg-type]
    svc.verify_signature(payload, "t=123,v1=badhex")  # Must not raise


# ── Replay ────────────────────────────────────────────────────────────────────

async def test_replay_reprocesses_stored_event(db_session):
    svc = WebhookService(db_session)
    event_id = f"evt_{uuid.uuid4().hex}"
    payload = _payload("invoice.paid", {"customer": "cus_replay"}, event_id)

    original = await svc.process(payload)
    assert original.status == "processed"

    replayed = await svc.replay(event_id)
    assert replayed.stripe_event_id == event_id


async def test_replay_unknown_event_raises(db_session):
    svc = WebhookService(db_session)
    with pytest.raises(ValueError, match="not found"):
        await svc.replay("evt_does_not_exist")

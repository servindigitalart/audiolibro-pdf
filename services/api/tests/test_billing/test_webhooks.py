"""
Webhook Service Tests
======================
Validates signature verification, idempotent processing, state transitions
triggered by Stripe events, replay safety, and error handling.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import time
import uuid

import pytest

from app.billing.webhook import WebhookService, InvalidSignature
from app.billing.constants import SubscriptionStatus




# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_signature(secret: str, payload: bytes, timestamp: int | None = None) -> str:
    ts = timestamp or int(time.time())
    signed = f"{ts}.{payload.decode()}"
    sig = hmac.new(secret.encode(), signed.encode(), hashlib.sha256).hexdigest()
    return f"t={ts},v1={sig}"


def _invoice_paid_event(customer_id: str, event_id: str | None = None) -> bytes:
    return json.dumps({
        "id": event_id or f"evt_{uuid.uuid4().hex}",
        "type": "invoice.paid",
        "data": {"object": {"customer": customer_id}},
    }).encode()


def _subscription_updated_event(customer_id: str, stripe_status: str, event_id: str | None = None) -> bytes:
    return json.dumps({
        "id": event_id or f"evt_{uuid.uuid4().hex}",
        "type": "customer.subscription.updated",
        "data": {"object": {"customer": customer_id, "status": stripe_status}},
    }).encode()


def _subscription_deleted_event(customer_id: str, event_id: str | None = None) -> bytes:
    return json.dumps({
        "id": event_id or f"evt_{uuid.uuid4().hex}",
        "type": "customer.subscription.deleted",
        "data": {"object": {"customer": customer_id}},
    }).encode()


# ── Signature validation ──────────────────────────────────────────────────────

def test_valid_signature_passes():
    secret = "whsec_test_secret"
    payload = b'{"id":"evt_1","type":"test"}'
    sig = _make_signature(secret, payload)

    svc = WebhookService.__new__(WebhookService)
    svc._secret = secret
    svc.verify_signature(payload, sig)  # must not raise


def test_invalid_signature_raises():
    secret = "whsec_correct"
    payload = b'{"id":"evt_1","type":"test"}'
    bad_sig = _make_signature("whsec_wrong", payload)

    svc = WebhookService.__new__(WebhookService)
    svc._secret = secret
    with pytest.raises(InvalidSignature):
        svc.verify_signature(payload, bad_sig)


def test_stale_timestamp_raises():
    secret = "whsec_test"
    payload = b'{"id":"evt_old","type":"test"}'
    old_ts = int(time.time()) - 400  # 400s ago → beyond 300s window
    sig = _make_signature(secret, payload, timestamp=old_ts)

    svc = WebhookService.__new__(WebhookService)
    svc._secret = secret
    with pytest.raises(InvalidSignature, match="too old"):
        svc.verify_signature(payload, sig)


def test_no_secret_skips_validation():
    svc = WebhookService.__new__(WebhookService)
    svc._secret = ""
    svc.verify_signature(b"anything", "t=0,v1=garbage")  # must not raise


def test_malformed_signature_header_raises():
    svc = WebhookService.__new__(WebhookService)
    svc._secret = "secret"
    with pytest.raises(InvalidSignature, match="Malformed"):
        svc.verify_signature(b"payload", "not_valid_format")


# ── Event processing ──────────────────────────────────────────────────────────

async def test_process_persists_event(db_session):
    svc = WebhookService(db_session)
    event_id = f"evt_{uuid.uuid4().hex}"
    payload = json.dumps({"id": event_id, "type": "invoice.paid",
                          "data": {"object": {"customer": "cus_unknown"}}}).encode()

    event = await svc.process(payload)

    assert event.stripe_event_id == event_id
    assert event.event_type == "invoice.paid"
    assert event.status == "processed"


async def test_process_is_idempotent(db_session):
    """Processing the same event twice returns the stored row, not a new one."""
    svc = WebhookService(db_session)
    event_id = f"evt_{uuid.uuid4().hex}"
    payload = json.dumps({"id": event_id, "type": "invoice.paid",
                          "data": {"object": {"customer": "cus_unknown"}}}).encode()

    event1 = await svc.process(payload)
    event2 = await svc.process(payload)

    assert event1.id == event2.id
    assert event2.status == "processed"


async def test_invoice_paid_transitions_user_to_active(db_session, db_user):
    db_user.stripe_customer_id = "cus_billing_test"
    db_user.subscription_status = "trial"
    await db_session.flush()

    svc = WebhookService(db_session)
    payload = _invoice_paid_event("cus_billing_test")
    await svc.process(payload)

    from app.billing.subscription import SubscriptionService
    sub_svc = SubscriptionService(db_session)
    status = await sub_svc.get_status(db_user.id)
    assert status == SubscriptionStatus.ACTIVE


async def test_subscription_updated_to_past_due(db_session, db_user):
    db_user.stripe_customer_id = "cus_past_due_test"
    db_user.subscription_status = "active"
    await db_session.flush()

    svc = WebhookService(db_session)
    payload = _subscription_updated_event("cus_past_due_test", "past_due")
    await svc.process(payload)

    from app.billing.subscription import SubscriptionService
    status = await SubscriptionService(db_session).get_status(db_user.id)
    assert status == SubscriptionStatus.PAST_DUE


async def test_subscription_deleted_transitions_to_canceled(db_session, db_user):
    db_user.stripe_customer_id = "cus_cancel_test"
    db_user.subscription_status = "active"
    await db_session.flush()

    svc = WebhookService(db_session)
    payload = _subscription_deleted_event("cus_cancel_test")
    await svc.process(payload)

    from app.billing.subscription import SubscriptionService
    status = await SubscriptionService(db_session).get_status(db_user.id)
    assert status == SubscriptionStatus.CANCELED


async def test_unknown_customer_id_does_not_raise(db_session):
    """Events for unknown customers must be persisted but not crash."""
    svc = WebhookService(db_session)
    payload = _invoice_paid_event("cus_does_not_exist")
    event = await svc.process(payload)
    assert event.status == "processed"


async def test_unknown_event_type_is_stored_but_ignored(db_session):
    svc = WebhookService(db_session)
    payload = json.dumps({"id": f"evt_{uuid.uuid4().hex}", "type": "payment_intent.created",
                          "data": {}}).encode()
    event = await svc.process(payload)
    assert event.status == "processed"


async def test_replay_reprocesses_stored_event(db_session, db_user):
    db_user.stripe_customer_id = "cus_replay_test"
    db_user.subscription_status = "trial"
    await db_session.flush()

    svc = WebhookService(db_session)
    payload = _invoice_paid_event("cus_replay_test", event_id="evt_replay_fixed")
    await svc.process(payload)

    # Reset user status to test replay
    db_user.subscription_status = "trial"
    await db_session.flush()

    event = await svc.replay("evt_replay_fixed")
    assert event.status == "processed"


async def test_replay_unknown_event_raises(db_session):
    svc = WebhookService(db_session)
    with pytest.raises(ValueError, match="not found"):
        await svc.replay("evt_nonexistent_xyz")

"""
Webhook Replay Storm Tests
===========================
Verifies that WebhookService handles high-volume duplicate delivery, replays,
out-of-order events, and malformed payloads without corrupting billing state.

Invariant enforced: I4 (each stripe_event_id exactly once in webhook_events).
"""
from __future__ import annotations

import json
import uuid

import pytest
from sqlalchemy import func, select

from app.billing.constants import SubscriptionStatus
from app.billing.models import WebhookEvent
from app.billing.subscription import SubscriptionService
from app.billing.webhook import WebhookService
from tests.chaos.financial_invariants import FinancialInvariantSuite


# ── Helpers ───────────────────────────────────────────────────────────────────

def _event(event_id: str, event_type: str, data: dict) -> bytes:
    return json.dumps({"id": event_id, "type": event_type, "data": data}).encode()


def _invoice_paid(customer_id: str, event_id: str | None = None) -> bytes:
    return _event(
        event_id or f"evt_{uuid.uuid4().hex}",
        "invoice.paid",
        {"object": {"customer": customer_id}},
    )


def _sub_updated(customer_id: str, status: str, event_id: str | None = None) -> bytes:
    return _event(
        event_id or f"evt_{uuid.uuid4().hex}",
        "customer.subscription.updated",
        {"object": {"customer": customer_id, "status": status}},
    )


def _sub_deleted(customer_id: str, event_id: str | None = None) -> bytes:
    return _event(
        event_id or f"evt_{uuid.uuid4().hex}",
        "customer.subscription.deleted",
        {"object": {"customer": customer_id}},
    )


# ── Idempotency under storm delivery ─────────────────────────────────────────

async def test_same_event_50_times_creates_one_row(db_session):
    """Processing the same stripe_event_id 50 times results in exactly one DB row."""
    svc = WebhookService(db_session)
    event_id = f"evt_storm_{uuid.uuid4().hex}"
    payload = _invoice_paid("cus_unknown", event_id=event_id)

    for _ in range(50):
        event = await svc.process(payload)
        assert event.stripe_event_id == event_id

    result = await db_session.execute(
        select(func.count()).select_from(WebhookEvent).where(
            WebhookEvent.stripe_event_id == event_id
        )
    )
    count = result.scalar_one()
    assert count == 1, f"Expected 1 webhook row, found {count}"


async def test_duplicate_event_returns_same_id(db_session):
    """Second call with same event_id returns the same WebhookEvent row."""
    svc = WebhookService(db_session)
    event_id = f"evt_dup_{uuid.uuid4().hex}"
    payload = _invoice_paid("cus_noone", event_id=event_id)

    ev1 = await svc.process(payload)
    ev2 = await svc.process(payload)

    assert ev1.id == ev2.id


async def test_storm_of_unique_events_all_processed(db_session):
    """25 distinct events all get persisted with status='processed'."""
    svc = WebhookService(db_session)
    event_ids = [f"evt_{uuid.uuid4().hex}" for _ in range(25)]

    for eid in event_ids:
        await svc.process(_invoice_paid("cus_storm", event_id=eid))

    result = await db_session.execute(
        select(func.count()).select_from(WebhookEvent).where(
            WebhookEvent.status == "processed"
        )
    )
    count = result.scalar_one()
    assert count >= 25


# ── State transition idempotency under storm ──────────────────────────────────

async def test_invoice_paid_storm_does_not_double_transition(db_session, active_chaos_user):
    """
    Repeated invoice.paid events for the same customer must not cause invalid
    state transitions after the first one succeeds.

    The first event transitions active→active (already active — no-op or
    caught as InvalidTransition). Subsequent events must not crash.
    """
    svc = WebhookService(db_session)
    cid = active_chaos_user.stripe_customer_id
    event_id = f"evt_paid_{uuid.uuid4().hex}"
    payload = _invoice_paid(cid, event_id=event_id)

    # First call processes normally
    ev1 = await svc.process(payload)
    assert ev1.status == "processed"

    # Subsequent identical calls are idempotent — same row returned
    for _ in range(10):
        ev = await svc.process(payload)
        assert ev.id == ev1.id


async def test_subscription_deleted_storm_idempotent(db_session, active_chaos_user):
    """
    Repeated subscription.deleted events: first one cancels, rest are idempotent.
    The user ends in 'canceled' state, not in an undefined state.
    """
    svc = WebhookService(db_session)
    sub_svc = SubscriptionService(db_session)
    cid = active_chaos_user.stripe_customer_id
    event_id = f"evt_del_{uuid.uuid4().hex}"
    payload = _sub_deleted(cid, event_id=event_id)

    for _ in range(5):
        await svc.process(payload)

    status = await sub_svc.get_status(active_chaos_user.id)
    assert status == SubscriptionStatus.CANCELED


# ── Replay ────────────────────────────────────────────────────────────────────

async def test_replay_processed_event_is_idempotent(db_session, active_chaos_user):
    """Replaying an already-processed event must be safe and return same row."""
    svc = WebhookService(db_session)
    cid = active_chaos_user.stripe_customer_id
    event_id = f"evt_replay_{uuid.uuid4().hex}"
    payload = _invoice_paid(cid, event_id=event_id)

    orig = await svc.process(payload)
    replayed = await svc.replay(event_id)

    assert orig.id == replayed.id
    assert replayed.status == "processed"


async def test_replay_unknown_event_raises_value_error(db_session):
    """Replaying a non-existent event_id must raise ValueError."""
    svc = WebhookService(db_session)
    with pytest.raises(ValueError, match="not found"):
        await svc.replay("evt_does_not_exist_xyz123")


async def test_replay_reprocesses_handlers(db_session, active_chaos_user):
    """
    Replay re-dispatches the handler.  After a subscription_deleted event is
    processed and the user is manually reset, replay should transition again.
    """
    svc = WebhookService(db_session)
    cid = active_chaos_user.stripe_customer_id
    event_id = f"evt_repro_{uuid.uuid4().hex}"

    await svc.process(_sub_deleted(cid, event_id=event_id))

    # Manually reset user back to active for the replay test
    from sqlalchemy import update
    from app.db.models.user import User
    await db_session.execute(
        update(User)
        .where(User.id == active_chaos_user.id)
        .values(subscription_status="active")
    )
    await db_session.flush()

    replayed = await svc.replay(event_id)
    assert replayed.status == "processed"

    sub_svc = SubscriptionService(db_session)
    status = await sub_svc.get_status(active_chaos_user.id)
    assert status == SubscriptionStatus.CANCELED


# ── Unknown and malformed events ──────────────────────────────────────────────

async def test_unknown_event_type_stored_not_crashed(db_session):
    """Unknown event types must be persisted with status='processed' (no crash)."""
    svc = WebhookService(db_session)
    event_id = f"evt_unk_{uuid.uuid4().hex}"
    payload = _event(event_id, "payment_intent.requires_action", {"data": {}})

    event = await svc.process(payload)
    assert event.status == "processed"
    assert event.event_type == "payment_intent.requires_action"


async def test_unknown_customer_id_does_not_crash(db_session):
    """Events for customers not in our DB must be stored without crashing."""
    svc = WebhookService(db_session)
    payload = _invoice_paid("cus_totally_unknown_xyz")
    event = await svc.process(payload)
    assert event.status == "processed"


async def test_10_different_event_types_all_processed(db_session):
    """A variety of event types are all stored correctly."""
    svc = WebhookService(db_session)
    event_types = [
        "invoice.paid",
        "invoice.payment_failed",
        "customer.subscription.updated",
        "customer.subscription.deleted",
        "customer.subscription.created",
        "payment_intent.succeeded",
        "payment_intent.payment_failed",
        "charge.succeeded",
        "charge.refunded",
        "checkout.session.completed",
    ]

    for et in event_types:
        eid = f"evt_{uuid.uuid4().hex}"
        payload = _event(eid, et, {"object": {"customer": "cus_unknown"}})
        event = await svc.process(payload)
        assert event.event_type == et


# ── I4 invariant ──────────────────────────────────────────────────────────────

async def test_i4_invariant_holds_after_storm(db_session, invariants):
    """After processing 20 events (some duplicated), I4 remains clean."""
    svc = WebhookService(db_session)

    # 10 unique events
    event_ids = [f"evt_{uuid.uuid4().hex}" for _ in range(10)]
    for eid in event_ids:
        await svc.process(_invoice_paid("cus_unknown", event_id=eid))

    # Replay each event 3 more times
    for eid in event_ids:
        for _ in range(3):
            await svc.process(_invoice_paid("cus_unknown", event_id=eid))

    violations = await invariants.check_all(db_session)
    assert not violations, f"Invariant violations after webhook storm: {violations}"

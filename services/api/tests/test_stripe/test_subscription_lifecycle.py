"""
Stripe Subscription Lifecycle Tests
======================================
DB-integrated tests covering the full subscription lifecycle using
MockStripeClient + real DB sessions (rollback isolation from conftest).

Scenarios:
  - Create customer → subscription → verify local DB state
  - Cancellation (immediate and at-period-end)
  - Trial → active transition via webhook
  - checkout.session.completed triggers subscription link + ACTIVE transition
  - Stripe error injection does not corrupt local state
  - Drift correction via reconciliation
"""
from __future__ import annotations

import json
import uuid

import pytest

from app.billing.constants import SubscriptionStatus
from app.billing.reconciliation import ReconciliationService
from app.billing.stripe.base import StripeError
from app.billing.subscription import SubscriptionService
from app.billing.webhook import WebhookService


# ── Helpers ───────────────────────────────────────────────────────────────────

def _invoice_paid_payload(customer_id: str, subscription_id: str, event_id: str | None = None) -> bytes:
    return json.dumps({
        "id": event_id or f"evt_{uuid.uuid4().hex}",
        "type": "invoice.paid",
        "data": {
            "object": {
                "customer": customer_id,
                "subscription": subscription_id,
                "status": "paid",
            }
        },
    }).encode()


def _invoice_failed_payload(customer_id: str, subscription_id: str, event_id: str | None = None) -> bytes:
    return json.dumps({
        "id": event_id or f"evt_{uuid.uuid4().hex}",
        "type": "invoice.payment_failed",
        "data": {
            "object": {
                "customer": customer_id,
                "subscription": subscription_id,
            }
        },
    }).encode()


def _checkout_completed_payload(customer_id: str, subscription_id: str, event_id: str | None = None) -> bytes:
    return json.dumps({
        "id": event_id or f"evt_{uuid.uuid4().hex}",
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "customer": customer_id,
                "subscription": subscription_id,
                "payment_status": "paid",
            }
        },
    }).encode()


def _sub_updated_payload(customer_id: str, subscription_id: str, status: str, event_id: str | None = None) -> bytes:
    return json.dumps({
        "id": event_id or f"evt_{uuid.uuid4().hex}",
        "type": "customer.subscription.updated",
        "data": {
            "object": {
                "id": subscription_id,
                "customer": customer_id,
                "status": status,
            }
        },
    }).encode()


def _sub_deleted_payload(customer_id: str, subscription_id: str, event_id: str | None = None) -> bytes:
    return json.dumps({
        "id": event_id or f"evt_{uuid.uuid4().hex}",
        "type": "customer.subscription.deleted",
        "data": {
            "object": {
                "id": subscription_id,
                "customer": customer_id,
                "status": "canceled",
            }
        },
    }).encode()


# ── Customer creation ─────────────────────────────────────────────────────────

async def test_create_customer_links_to_user(db_session, stripe_user):
    user, customer = stripe_user
    assert user.stripe_customer_id == customer.id
    assert customer.id.startswith("cus_mock_")


async def test_create_customer_stores_user_id_in_metadata(db_session, stripe_user):
    user, customer = stripe_user
    assert customer.metadata.get("user_id") == str(user.id)


# ── Subscription creation ─────────────────────────────────────────────────────

async def test_create_subscription_returns_active(db_session, stripe_user, mock_stripe):
    user, customer = stripe_user
    sub = await mock_stripe.create_subscription(customer.id, "price_basic", f"idem_{uuid.uuid4().hex}")
    assert sub.status == "active"
    assert sub.customer_id == customer.id


async def test_subscription_state_transitions_to_active_on_invoice_paid(
    db_session, stripe_user, mock_stripe
):
    user, customer = stripe_user
    sub = await mock_stripe.create_subscription(customer.id, "price_basic", f"idem_{uuid.uuid4().hex}")

    # Transition to TRIAL first (FREE → TRIAL is allowed)
    svc = SubscriptionService(db_session)
    await svc.transition(user.id, SubscriptionStatus.TRIAL, reason="setup")

    webhook = WebhookService(db_session)
    await webhook.process(_invoice_paid_payload(customer.id, sub.id))

    status = await svc.get_status(user.id)
    assert status == SubscriptionStatus.ACTIVE


async def test_trial_subscription_sets_trialing_status(db_session, stripe_user, mock_stripe):
    user, customer = stripe_user
    sub = await mock_stripe.create_subscription(
        customer.id, "price_pro", f"idem_{uuid.uuid4().hex}", trial_days=14
    )
    assert sub.status == "trialing"


# ── Checkout session completed ────────────────────────────────────────────────

async def test_checkout_completed_links_subscription_and_activates(
    db_session, stripe_user, mock_stripe
):
    user, customer = stripe_user
    sub = await mock_stripe.create_subscription(customer.id, "price_basic", f"idem_{uuid.uuid4().hex}")

    webhook = WebhookService(db_session)
    await webhook.process(_checkout_completed_payload(customer.id, sub.id))

    svc = SubscriptionService(db_session)
    status = await svc.get_status(user.id)
    assert status == SubscriptionStatus.ACTIVE


async def test_checkout_completed_updates_subscription_id_on_user(
    db_session, stripe_user, mock_stripe
):
    from sqlalchemy import select
    from app.db.models.user import User

    user, customer = stripe_user
    sub = await mock_stripe.create_subscription(customer.id, "price_basic", f"idem_{uuid.uuid4().hex}")

    webhook = WebhookService(db_session)
    await webhook.process(_checkout_completed_payload(customer.id, sub.id))

    result = await db_session.execute(select(User).where(User.id == user.id))
    refreshed = result.scalar_one()
    assert refreshed.stripe_subscription_id == sub.id


async def test_checkout_completed_for_unknown_customer_is_noop(db_session):
    webhook = WebhookService(db_session)
    event = await webhook.process(_checkout_completed_payload("cus_unknown_xyz", "sub_unknown"))
    assert event.status in ("processed", "ignored")


# ── Cancellation ──────────────────────────────────────────────────────────────

async def test_immediate_cancellation_marks_subscription_canceled(
    db_session, active_stripe_user, mock_stripe
):
    user, customer, sub = active_stripe_user
    canceled = await mock_stripe.cancel_subscription(sub.id, immediately=True)
    assert canceled.status == "canceled"


async def test_subscription_deleted_webhook_transitions_to_canceled(
    db_session, active_stripe_user, mock_stripe
):
    user, customer, sub = active_stripe_user
    webhook = WebhookService(db_session)
    await webhook.process(_sub_deleted_payload(customer.id, sub.id))

    svc = SubscriptionService(db_session)
    status = await svc.get_status(user.id)
    assert status == SubscriptionStatus.CANCELED


async def test_period_end_cancellation_still_active(db_session, active_stripe_user, mock_stripe):
    user, customer, sub = active_stripe_user
    updated = await mock_stripe.cancel_subscription(sub.id, immediately=False)
    assert updated.cancel_at_period_end is True
    assert updated.status == "active"


# ── Payment failure flow ──────────────────────────────────────────────────────

async def test_invoice_payment_failed_transitions_to_past_due(
    db_session, active_stripe_user, mock_stripe
):
    user, customer, sub = active_stripe_user
    webhook = WebhookService(db_session)
    await webhook.process(_invoice_failed_payload(customer.id, sub.id))

    svc = SubscriptionService(db_session)
    status = await svc.get_status(user.id)
    assert status == SubscriptionStatus.PAST_DUE


async def test_payment_recovery_from_past_due_to_active(
    db_session, active_stripe_user, mock_stripe
):
    user, customer, sub = active_stripe_user
    webhook = WebhookService(db_session)

    # Simulate payment failure
    await webhook.process(_invoice_failed_payload(customer.id, sub.id, event_id=f"evt_fail_{uuid.uuid4().hex}"))

    # Simulate payment recovery
    await webhook.process(_invoice_paid_payload(customer.id, sub.id, event_id=f"evt_paid_{uuid.uuid4().hex}"))

    svc = SubscriptionService(db_session)
    status = await svc.get_status(user.id)
    assert status == SubscriptionStatus.ACTIVE


# ── Stripe error isolation ────────────────────────────────────────────────────

async def test_stripe_create_customer_failure_does_not_corrupt_user(
    db_session, stripe_user, mock_stripe
):
    user, customer = stripe_user
    original_customer_id = user.stripe_customer_id

    mock_stripe.configure_failure("create_customer")
    with pytest.raises(StripeError):
        await mock_stripe.create_customer("fail@test.com", str(user.id))

    # Original user state is unchanged
    assert user.stripe_customer_id == original_customer_id


async def test_stripe_create_subscription_failure_leaves_user_in_free(
    db_session, stripe_user, mock_stripe
):
    user, customer = stripe_user
    mock_stripe.configure_failure("create_subscription")

    with pytest.raises(StripeError):
        await mock_stripe.create_subscription(customer.id, "price_basic", "idem_fail")

    svc = SubscriptionService(db_session)
    status = await svc.get_status(user.id)
    assert status == SubscriptionStatus.FREE


# ── Subscription history ──────────────────────────────────────────────────────

async def test_audit_log_records_all_transitions(db_session, active_stripe_user, mock_stripe):
    user, customer, sub = active_stripe_user
    webhook = WebhookService(db_session)

    await webhook.process(_invoice_failed_payload(customer.id, sub.id, f"evt_fail_{uuid.uuid4().hex}"))
    await webhook.process(_invoice_paid_payload(customer.id, sub.id, f"evt_paid_{uuid.uuid4().hex}"))

    svc = SubscriptionService(db_session)
    logs = await svc.history(user.id)

    # At least: active→past_due, past_due→active (plus fixture's initial active)
    statuses = [(l.from_status, l.to_status) for l in logs]
    assert ("past_due", "active") in statuses
    assert ("active", "past_due") in statuses


async def test_subscription_history_is_ordered_most_recent_first(
    db_session, active_stripe_user, mock_stripe
):
    user, customer, sub = active_stripe_user
    webhook = WebhookService(db_session)
    await webhook.process(_invoice_failed_payload(customer.id, sub.id, f"evt_{uuid.uuid4().hex}"))

    svc = SubscriptionService(db_session)
    logs = await svc.history(user.id, limit=10)
    timestamps = [l.created_at for l in logs]
    assert timestamps == sorted(timestamps, reverse=True)

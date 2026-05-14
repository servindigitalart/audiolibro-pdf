"""
Reconciliation Service Tests
================================
Tests ReconciliationService with real DB + MockStripeClient.

Scenarios:
  - No drift → outcome "ok"
  - Drift detected → corrected and audit-logged
  - User has no Stripe customer → outcome "no_stripe_customer"
  - Stripe API error → outcome "error" (no DB corruption)
  - Bulk reconciliation returns correct aggregate stats
  - Stripe "active" but local "past_due" → synced to active
  - Stripe "canceled" but local "active" → synced to canceled
  - Stripe "trialing" but local "free" → synced to trial
  - No subscriptions on Stripe + local active → synced to canceled
"""
from __future__ import annotations

import uuid

import pytest

from app.billing.constants import SubscriptionStatus
from app.billing.reconciliation import ReconciliationService
from app.billing.stripe.base import StripeError
from app.billing.subscription import SubscriptionService
from app.db.models.user import User


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _make_user(db_session, *, plan_tier="FREE", subscription_status="free", stripe_customer_id=None):
    user = User(
        id=uuid.uuid4(),
        email=f"recon_{uuid.uuid4().hex[:8]}@test.internal",
        hashed_password="$2b$12$fakehash",
        is_active=True,
        is_verified=True,
        plan_tier=plan_tier,
        subscription_status=subscription_status,
        stripe_customer_id=stripe_customer_id,
    )
    db_session.add(user)
    await db_session.flush()
    return user


# ── No drift ──────────────────────────────────────────────────────────────────

async def test_no_drift_returns_ok(db_session, mock_stripe):
    customer = await mock_stripe.create_customer("ok@test.internal", "uid")
    user = await _make_user(db_session, subscription_status="active", stripe_customer_id=customer.id)
    await mock_stripe.create_subscription(customer.id, "price_basic", f"k_{uuid.uuid4().hex}")

    svc = ReconciliationService(db_session)
    result = await svc.reconcile_user(user, mock_stripe)

    assert result.outcome == "ok"
    assert result.drift_detected is False


async def test_no_drift_active_subscription_is_ok(db_session, active_stripe_user, mock_stripe):
    user, customer, sub = active_stripe_user
    svc = ReconciliationService(db_session)
    result = await svc.reconcile_user(user, mock_stripe)
    assert result.outcome == "ok"


# ── Drift correction ──────────────────────────────────────────────────────────

async def test_stripe_active_local_past_due_synced_to_active(db_session, mock_stripe):
    customer = await mock_stripe.create_customer("drift1@test.internal", "uid")
    user = await _make_user(db_session, subscription_status="past_due", stripe_customer_id=customer.id)
    await mock_stripe.create_subscription(customer.id, "price_basic", f"k_{uuid.uuid4().hex}")

    svc = ReconciliationService(db_session)
    result = await svc.reconcile_user(user, mock_stripe)

    assert result.outcome == "synced"
    assert result.drift_detected is True
    assert result.previous_status == "past_due"
    assert result.new_status == "active"


async def test_stripe_canceled_local_active_synced_to_canceled(db_session, mock_stripe):
    customer = await mock_stripe.create_customer("drift2@test.internal", "uid")
    user = await _make_user(db_session, subscription_status="active", stripe_customer_id=customer.id)
    sub = await mock_stripe.create_subscription(customer.id, "price_basic", f"k_{uuid.uuid4().hex}")
    await mock_stripe.cancel_subscription(sub.id, immediately=True)

    svc = ReconciliationService(db_session)
    result = await svc.reconcile_user(user, mock_stripe)

    assert result.outcome == "synced"
    assert result.new_status == "canceled"


async def test_stripe_trialing_local_free_synced_to_trial(db_session, mock_stripe):
    customer = await mock_stripe.create_customer("drift3@test.internal", "uid")
    user = await _make_user(db_session, subscription_status="free", stripe_customer_id=customer.id)
    await mock_stripe.create_subscription(
        customer.id, "price_pro", f"k_{uuid.uuid4().hex}", trial_days=14
    )

    svc = ReconciliationService(db_session)
    result = await svc.reconcile_user(user, mock_stripe)

    assert result.outcome == "synced"
    assert result.new_status == "trial"


async def test_no_stripe_subscriptions_active_local_synced_to_canceled(db_session, mock_stripe):
    customer = await mock_stripe.create_customer("drift4@test.internal", "uid")
    user = await _make_user(db_session, subscription_status="active", stripe_customer_id=customer.id)
    # No subscriptions created in Stripe

    svc = ReconciliationService(db_session)
    result = await svc.reconcile_user(user, mock_stripe)

    assert result.outcome == "synced"
    assert result.new_status == "canceled"


async def test_drift_correction_creates_audit_log(db_session, mock_stripe):
    customer = await mock_stripe.create_customer("audit@test.internal", "uid")
    user = await _make_user(db_session, subscription_status="past_due", stripe_customer_id=customer.id)
    await mock_stripe.create_subscription(customer.id, "price_basic", f"k_{uuid.uuid4().hex}")

    svc = ReconciliationService(db_session)
    await svc.reconcile_user(user, mock_stripe)

    sub_svc = SubscriptionService(db_session)
    logs = await sub_svc.history(user.id)
    assert len(logs) >= 1
    assert any("reconciliation" in (l.reason or "") for l in logs)


# ── No Stripe customer ────────────────────────────────────────────────────────

async def test_no_stripe_customer_id_returns_no_stripe_customer(db_session, mock_stripe):
    user = await _make_user(db_session, stripe_customer_id=None)
    svc = ReconciliationService(db_session)
    result = await svc.reconcile_user(user, mock_stripe)
    assert result.outcome == "no_stripe_customer"


async def test_no_stripe_customer_does_not_change_local_status(db_session, mock_stripe):
    user = await _make_user(db_session, subscription_status="active", stripe_customer_id=None)
    svc = ReconciliationService(db_session)
    await svc.reconcile_user(user, mock_stripe)

    # Status should be unchanged — we don't know if it's drifted
    sub_svc = SubscriptionService(db_session)
    status = await sub_svc.get_status(user.id)
    assert status == SubscriptionStatus.ACTIVE


# ── Stripe API error ──────────────────────────────────────────────────────────

async def test_stripe_api_error_returns_error_outcome(db_session, mock_stripe):
    customer = await mock_stripe.create_customer("err@test.internal", "uid")
    user = await _make_user(db_session, subscription_status="active", stripe_customer_id=customer.id)

    mock_stripe.configure_failure("list_customer_subscriptions")
    svc = ReconciliationService(db_session)
    result = await svc.reconcile_user(user, mock_stripe)

    assert result.outcome == "error"
    assert result.drift_detected is False


async def test_stripe_api_error_does_not_mutate_local_status(db_session, mock_stripe):
    customer = await mock_stripe.create_customer("safe@test.internal", "uid")
    user = await _make_user(db_session, subscription_status="active", stripe_customer_id=customer.id)

    mock_stripe.configure_failure("list_customer_subscriptions")
    svc = ReconciliationService(db_session)
    await svc.reconcile_user(user, mock_stripe)

    sub_svc = SubscriptionService(db_session)
    status = await sub_svc.get_status(user.id)
    assert status == SubscriptionStatus.ACTIVE


# ── Bulk reconciliation ───────────────────────────────────────────────────────

async def test_bulk_reconcile_returns_report(db_session, mock_stripe):
    # Two users: one drifted, one clean
    c1 = await mock_stripe.create_customer("bulk1@test.internal", "u1")
    u1 = await _make_user(db_session, subscription_status="active", stripe_customer_id=c1.id)
    await mock_stripe.create_subscription(c1.id, "price_basic", f"k_{uuid.uuid4().hex}")

    c2 = await mock_stripe.create_customer("bulk2@test.internal", "u2")
    u2 = await _make_user(db_session, subscription_status="past_due", stripe_customer_id=c2.id)
    await mock_stripe.create_subscription(c2.id, "price_basic", f"k_{uuid.uuid4().hex}")

    svc = ReconciliationService(db_session)
    report = await svc.reconcile_bulk(mock_stripe, limit=10)

    assert report.users_checked >= 2
    assert report.synced >= 1
    assert report.errors == 0
    assert 0.0 <= report.drift_rate <= 1.0


async def test_bulk_reconcile_drift_rate_calculation(db_session, mock_stripe):
    # Three drifted users + one clean
    for i in range(3):
        c = await mock_stripe.create_customer(f"drift_bulk_{i}@test.internal", f"u{i}")
        await _make_user(db_session, subscription_status="past_due", stripe_customer_id=c.id)
        await mock_stripe.create_subscription(c.id, "price_basic", f"k_{uuid.uuid4().hex}_{i}")

    c_ok = await mock_stripe.create_customer("ok_bulk@test.internal", "uok")
    await _make_user(db_session, subscription_status="active", stripe_customer_id=c_ok.id)
    await mock_stripe.create_subscription(c_ok.id, "price_basic", f"k_ok_{uuid.uuid4().hex}")

    svc = ReconciliationService(db_session)
    report = await svc.reconcile_bulk(mock_stripe, limit=10)

    assert report.drift_rate == round(report.synced / report.users_checked, 4)


async def test_bulk_reconcile_with_no_stripe_users_returns_empty(db_session, mock_stripe):
    # Users without stripe_customer_id are skipped
    await _make_user(db_session, stripe_customer_id=None)
    await _make_user(db_session, stripe_customer_id=None)

    svc = ReconciliationService(db_session)
    report = await svc.reconcile_bulk(mock_stripe, limit=10)

    assert report.synced == 0
    assert report.errors == 0


async def test_bulk_reconcile_error_is_not_fatal(db_session, mock_stripe):
    c1 = await mock_stripe.create_customer("err_bulk@test.internal", "u1")
    await _make_user(db_session, subscription_status="active", stripe_customer_id=c1.id)

    mock_stripe.configure_failure("list_customer_subscriptions")

    svc = ReconciliationService(db_session)
    report = await svc.reconcile_bulk(mock_stripe, limit=10)

    # Error is counted but doesn't abort the run
    assert report.errors >= 1


# ── ReconciliationResult properties ──────────────────────────────────────────

async def test_result_is_ok_for_no_drift(db_session, mock_stripe):
    customer = await mock_stripe.create_customer("prop@test.internal", "uid")
    user = await _make_user(db_session, subscription_status="active", stripe_customer_id=customer.id)
    await mock_stripe.create_subscription(customer.id, "price_basic", f"k_{uuid.uuid4().hex}")

    svc = ReconciliationService(db_session)
    result = await svc.reconcile_user(user, mock_stripe)

    assert result.is_ok is True


async def test_result_is_ok_for_no_stripe_customer(db_session, mock_stripe):
    user = await _make_user(db_session, stripe_customer_id=None)
    svc = ReconciliationService(db_session)
    result = await svc.reconcile_user(user, mock_stripe)
    assert result.is_ok is True


async def test_result_is_not_ok_for_error(db_session, mock_stripe):
    customer = await mock_stripe.create_customer("notok@test.internal", "uid")
    user = await _make_user(db_session, subscription_status="active", stripe_customer_id=customer.id)

    mock_stripe.configure_failure("list_customer_subscriptions")
    svc = ReconciliationService(db_session)
    result = await svc.reconcile_user(user, mock_stripe)

    assert result.is_ok is False

"""
MockStripeClient Unit Tests
============================
Verifies the mock behaves exactly as production Stripe should:
  - correct data shapes returned
  - call log records every operation
  - failure injection works deterministically
  - state mutations (set_subscription_status) are visible
  - reset() clears all state
"""
from __future__ import annotations

import pytest

from app.billing.stripe.base import StripeCustomer, StripeError, StripeSubscription
from app.billing.stripe.mock import MockStripeClient


# ── Customer operations ───────────────────────────────────────────────────────

async def test_create_customer_returns_valid_id(mock_stripe):
    customer = await mock_stripe.create_customer("user@test.com", "user-123")
    assert customer.id.startswith("cus_mock_")
    assert customer.email == "user@test.com"
    assert customer.metadata["user_id"] == "user-123"


async def test_create_customer_recorded_in_call_log(mock_stripe):
    await mock_stripe.create_customer("a@test.com", "uid-1")
    assert mock_stripe.call_count("create_customer") == 1
    assert mock_stripe.calls("create_customer")[0]["email"] == "a@test.com"


async def test_get_customer_returns_created_customer(mock_stripe):
    c = await mock_stripe.create_customer("b@test.com", "uid-2")
    fetched = await mock_stripe.get_customer(c.id)
    assert fetched is not None
    assert fetched.id == c.id
    assert fetched.email == "b@test.com"


async def test_get_unknown_customer_returns_none(mock_stripe):
    result = await mock_stripe.get_customer("cus_nonexistent")
    assert result is None


# ── Subscription operations ───────────────────────────────────────────────────

async def test_create_subscription_active_by_default(mock_stripe):
    c = await mock_stripe.create_customer("c@test.com", "uid-3")
    sub = await mock_stripe.create_subscription(c.id, "price_basic", "idem-1")
    assert sub.id.startswith("sub_mock_")
    assert sub.status == "active"
    assert sub.customer_id == c.id
    assert sub.price_id == "price_basic"


async def test_create_subscription_trial_when_trial_days_set(mock_stripe):
    c = await mock_stripe.create_customer("d@test.com", "uid-4")
    sub = await mock_stripe.create_subscription(c.id, "price_pro", "idem-2", trial_days=14)
    assert sub.status == "trialing"


async def test_create_subscription_idempotency_key_stored(mock_stripe):
    c = await mock_stripe.create_customer("e@test.com", "uid-5")
    await mock_stripe.create_subscription(c.id, "price_basic", "key-xyz")
    call = mock_stripe.calls("create_subscription")[0]
    assert call["idempotency_key"] == "key-xyz"


async def test_cancel_subscription_immediately(mock_stripe):
    c = await mock_stripe.create_customer("f@test.com", "uid-6")
    sub = await mock_stripe.create_subscription(c.id, "price_basic", "idem-3")
    canceled = await mock_stripe.cancel_subscription(sub.id, immediately=True)
    assert canceled.status == "canceled"


async def test_cancel_subscription_at_period_end(mock_stripe):
    c = await mock_stripe.create_customer("g@test.com", "uid-7")
    sub = await mock_stripe.create_subscription(c.id, "price_basic", "idem-4")
    updated = await mock_stripe.cancel_subscription(sub.id, immediately=False)
    assert updated.cancel_at_period_end is True
    assert updated.status == "active"  # still active until period ends


async def test_cancel_nonexistent_subscription_raises(mock_stripe):
    with pytest.raises(StripeError) as exc_info:
        await mock_stripe.cancel_subscription("sub_nonexistent")
    assert exc_info.value.code == "resource_missing"
    assert exc_info.value.http_status == 404


async def test_get_subscription_returns_correct_sub(mock_stripe):
    c = await mock_stripe.create_customer("h@test.com", "uid-8")
    sub = await mock_stripe.create_subscription(c.id, "price_basic", "idem-5")
    fetched = await mock_stripe.get_subscription(sub.id)
    assert fetched is not None
    assert fetched.id == sub.id


async def test_get_unknown_subscription_returns_none(mock_stripe):
    result = await mock_stripe.get_subscription("sub_nonexistent")
    assert result is None


async def test_list_customer_subscriptions(mock_stripe):
    c = await mock_stripe.create_customer("i@test.com", "uid-9")
    sub1 = await mock_stripe.create_subscription(c.id, "price_basic", "idem-6")
    sub2 = await mock_stripe.create_subscription(c.id, "price_pro", "idem-7")
    subs = await mock_stripe.list_customer_subscriptions(c.id)
    ids = {s.id for s in subs}
    assert sub1.id in ids and sub2.id in ids


async def test_list_subscriptions_with_status_filter(mock_stripe):
    c = await mock_stripe.create_customer("j@test.com", "uid-10")
    sub = await mock_stripe.create_subscription(c.id, "price_basic", "idem-8")
    await mock_stripe.cancel_subscription(sub.id, immediately=True)

    active = await mock_stripe.list_customer_subscriptions(c.id, status="active")
    assert len(active) == 0

    all_subs = await mock_stripe.list_customer_subscriptions(c.id, status="all")
    assert len(all_subs) == 1


async def test_list_subscriptions_empty_for_unknown_customer(mock_stripe):
    subs = await mock_stripe.list_customer_subscriptions("cus_nobody")
    assert subs == []


# ── Checkout and portal ───────────────────────────────────────────────────────

async def test_create_checkout_session_returns_session(mock_stripe):
    c = await mock_stripe.create_customer("k@test.com", "uid-11")
    session = await mock_stripe.create_checkout_session(
        customer_id=c.id,
        price_id="price_basic",
        success_url="https://app.com/success",
        cancel_url="https://app.com/cancel",
        idempotency_key="checkout-idem-1",
    )
    assert session.id.startswith("cs_mock_")
    assert session.customer_id == c.id
    assert session.subscription_id is not None
    assert session.status == "complete"


async def test_create_billing_portal_session(mock_stripe):
    c = await mock_stripe.create_customer("l@test.com", "uid-12")
    url = await mock_stripe.create_billing_portal_session(c.id, "https://app.com/billing")
    assert url.startswith("https://billing.stripe.com/portal/mock/")


# ── Failure injection ─────────────────────────────────────────────────────────

async def test_configure_failure_raises_on_next_call(mock_stripe):
    mock_stripe.configure_failure("create_customer")
    with pytest.raises(StripeError) as exc_info:
        await mock_stripe.create_customer("fail@test.com", "uid-fail")
    assert exc_info.value.code == "mock_injected_error"


async def test_failure_is_one_shot(mock_stripe):
    """After the injected failure fires, the next call succeeds."""
    mock_stripe.configure_failure("create_customer")
    try:
        await mock_stripe.create_customer("fail@test.com", "uid-fail")
    except StripeError:
        pass
    # Second call should succeed
    c = await mock_stripe.create_customer("ok@test.com", "uid-ok")
    assert c.id.startswith("cus_mock_")


async def test_wildcard_failure_hits_any_method(mock_stripe):
    mock_stripe.configure_failure("*")
    with pytest.raises(StripeError):
        await mock_stripe.create_customer("any@test.com", "uid-any")


async def test_clear_failure_removes_injected_error(mock_stripe):
    mock_stripe.configure_failure("create_subscription")
    mock_stripe.clear_failure()
    c = await mock_stripe.create_customer("ok@test.com", "uid-ok")
    sub = await mock_stripe.create_subscription(c.id, "price_basic", "idem")
    assert sub is not None


# ── State mutation ────────────────────────────────────────────────────────────

async def test_set_subscription_status(mock_stripe):
    """set_subscription_status simulates Stripe-side state change (e.g., payment failure)."""
    c = await mock_stripe.create_customer("m@test.com", "uid-13")
    sub = await mock_stripe.create_subscription(c.id, "price_basic", "idem-9")
    assert sub.status == "active"

    mock_stripe.set_subscription_status(sub.id, "past_due")
    fetched = await mock_stripe.get_subscription(sub.id)
    assert fetched.status == "past_due"


# ── Reset ─────────────────────────────────────────────────────────────────────

async def test_reset_clears_all_state(mock_stripe):
    c = await mock_stripe.create_customer("n@test.com", "uid-14")
    await mock_stripe.create_subscription(c.id, "price_basic", "idem-10")

    mock_stripe.reset()
    assert mock_stripe.call_count("create_customer") == 0
    assert await mock_stripe.get_customer(c.id) is None


# ── Factory ───────────────────────────────────────────────────────────────────

def test_factory_returns_mock_by_default():
    """With STRIPE_MODE=mock (default), factory returns MockStripeClient."""
    from app.billing.stripe.factory import get_stripe_provider
    provider = get_stripe_provider()
    assert isinstance(provider, MockStripeClient)


def test_factory_rejects_unknown_mode():
    from app.billing.stripe.factory import get_stripe_provider
    from app.core.config import settings
    import pytest
    original = settings.stripe_mode
    try:
        settings.__dict__["stripe_mode"] = "invalid"
        with pytest.raises(ValueError, match="Unknown STRIPE_MODE"):
            get_stripe_provider()
    finally:
        settings.__dict__["stripe_mode"] = original

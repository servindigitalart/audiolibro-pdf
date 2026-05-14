"""
Stripe Integration Test Fixtures
==================================
All Stripe tests use MockStripeClient — no real API keys required.
DB fixtures are inherited from the parent conftest (rollback isolation).

Fixtures:
  mock_stripe     — Fresh MockStripeClient per test
  stripe_user     — DB user with Stripe customer already linked
  active_stripe_user — DB user in 'active' subscription state
"""
from __future__ import annotations

import uuid

import pytest

from app.billing.stripe.mock import MockStripeClient


@pytest.fixture
def mock_stripe() -> MockStripeClient:
    """Fresh MockStripeClient per test — all state cleared."""
    return MockStripeClient()


@pytest.fixture
async def stripe_user(db_session, mock_stripe):
    """
    A real User row in DB with a Stripe customer already created.
    Returns (user, stripe_customer) tuple.
    """
    from app.db.models.user import User

    user = User(
        id=uuid.uuid4(),
        email=f"stripe_{uuid.uuid4().hex[:8]}@test.internal",
        hashed_password="$2b$12$fakehash",
        is_active=True,
        is_verified=True,
        plan_tier="FREE",
        subscription_status="free",
    )
    db_session.add(user)
    await db_session.flush()

    customer = await mock_stripe.create_customer(user.email, str(user.id))
    user.stripe_customer_id = customer.id
    await db_session.flush()

    return user, customer


@pytest.fixture
async def active_stripe_user(db_session, mock_stripe):
    """
    A real User row already in 'active' state with a Stripe subscription.
    Returns (user, customer, subscription) tuple.
    """
    from app.db.models.user import User

    user = User(
        id=uuid.uuid4(),
        email=f"active_{uuid.uuid4().hex[:8]}@test.internal",
        hashed_password="$2b$12$fakehash",
        is_active=True,
        is_verified=True,
        plan_tier="PRO",
        subscription_status="active",
        stripe_customer_id=f"cus_fixture_{uuid.uuid4().hex[:10]}",
    )
    db_session.add(user)
    await db_session.flush()

    customer = await mock_stripe.create_customer(user.email, str(user.id))
    user.stripe_customer_id = customer.id

    sub = await mock_stripe.create_subscription(
        customer.id,
        price_id="price_pro_monthly",
        idempotency_key=f"fixture_{uuid.uuid4().hex}",
    )
    user.stripe_subscription_id = sub.id
    await db_session.flush()

    return user, customer, sub

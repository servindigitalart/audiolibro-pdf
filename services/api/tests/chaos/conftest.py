"""
Chaos Test Fixtures
====================
Shared fixtures for the chaos engineering test suite.

Designed to work alongside the parent conftest.py — db_session (with
its savepoint-rollback isolation) and mock_redis (autouse) are inherited.

Chaos tests layer on top with:
  - failing_redis  : FailingRedis with injectable fault modes
  - invariants     : FinancialInvariantSuite for post-condition assertions
  - chaos_user     : A real User row (FK anchor) rolled back with db_session
"""
from __future__ import annotations

import uuid

import pytest

from tests.chaos.financial_invariants import FinancialInvariantSuite
from tests.chaos.injectors import FailingRedis


@pytest.fixture
def failing_redis() -> FailingRedis:
    """Fresh FailingRedis — no failures configured by default."""
    return FailingRedis()


@pytest.fixture
def invariants() -> FinancialInvariantSuite:
    """Financial invariant suite for post-condition assertions."""
    return FinancialInvariantSuite()


@pytest.fixture
async def chaos_user(db_session):
    """
    A real User row for chaos tests that need FK relationships.
    Rolled back automatically by the parent db_session fixture.
    Uses a unique email to avoid conflicts across concurrent fixture calls.
    """
    from app.db.models.user import User

    user = User(
        id=uuid.uuid4(),
        email=f"chaos_{uuid.uuid4().hex[:8]}@test.internal",
        hashed_password="$2b$12$fakehashforchaostesting000",
        is_active=True,
        is_verified=True,
        plan_tier="FREE",
        subscription_status="free",
    )
    db_session.add(user)
    await db_session.flush()
    return user


@pytest.fixture
async def active_chaos_user(db_session):
    """A chaos user pre-set to 'active' subscription status."""
    from app.db.models.user import User

    user = User(
        id=uuid.uuid4(),
        email=f"chaos_active_{uuid.uuid4().hex[:8]}@test.internal",
        hashed_password="$2b$12$fakehashforchaostesting000",
        is_active=True,
        is_verified=True,
        plan_tier="PRO",
        subscription_status="active",
        stripe_customer_id=f"cus_chaos_{uuid.uuid4().hex[:12]}",
    )
    db_session.add(user)
    await db_session.flush()
    return user

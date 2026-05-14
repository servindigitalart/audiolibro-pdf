"""
Billing Test Fixtures
=====================
Provides isolated fixtures for billing unit/integration tests.

All DB tests reuse the session-level rollback pattern from the parent conftest
(db_session fixture).  Redis is always FakeRedis from tests/fakes.py.
"""
from __future__ import annotations

import uuid

import pytest

from tests.fakes import FakeRedis


@pytest.fixture
def fake_redis() -> FakeRedis:
    """Fresh FakeRedis with hash + pipeline support for billing tests."""
    return FakeRedis()


@pytest.fixture
def user_id() -> uuid.UUID:
    """Stable test user UUID (no DB row needed for pure service tests)."""
    return uuid.UUID("00000000-0000-0000-0000-000000000001")


@pytest.fixture
async def db_user(db_session):
    """
    A real User row in the test DB for tests that need FK relationships.
    The parent conftest's db_session rolls back after the test.
    """
    from app.db.models.user import User
    user = User(
        id=uuid.UUID("00000000-0000-0000-0000-000000000099"),
        email=f"billing_test_{uuid.uuid4().hex[:6]}@test.com",
        hashed_password="$2b$12$fakehash",
        is_active=True,
        is_verified=True,
        plan_tier="FREE",
        subscription_status="free",
    )
    db_session.add(user)
    await db_session.flush()
    return user

"""
Test Factories
==============
Factory Boy factories for ORM models.

Design decisions
----------------
- factory.Factory (not SQLAlchemyModelFactory) because we use async SQLAlchemy.
  Async DB writes don't fit Factory Boy's sync persistence model.
- All factories use factory.build() — instances are constructed in memory.
- Use create_user() / create_admin() helpers to persist and refresh objects.
- hashed_password is computed once and cached (bcrypt is intentionally slow).
- Sequence-based emails guarantee uniqueness across tests in the same run.
"""

from __future__ import annotations

from uuid import uuid4

import factory
from factory import LazyFunction, Sequence
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password
from app.db.models.user import User


# Bcrypt is slow; compute once and reuse across all UserFactory.build() calls.
_cached_password_hash: str | None = None


def _get_password_hash() -> str:
    global _cached_password_hash
    if _cached_password_hash is None:
        _cached_password_hash = hash_password(DEFAULT_PASSWORD)
    return _cached_password_hash


DEFAULT_PASSWORD = "Test12345!"


class UserFactory(factory.Factory):
    """
    Builds User ORM instances without touching the database.

    Usage
    -----
    # In-memory only (useful for unit tests):
    user = UserFactory.build()
    user = UserFactory.build(email="custom@example.com", role="admin")

    # Persisted to test DB (use inside async fixtures / tests):
    user = await create_user(db_session)
    admin = await create_admin(db_session, email="boss@example.com")
    """

    class Meta:
        model = User

    # Set explicitly so user.id is available immediately after build(),
    # before any DB flush.
    id = LazyFunction(uuid4)

    # Sequence gives deterministic, collision-free emails within a session.
    email = Sequence(lambda n: f"user_{n}@example.com")

    hashed_password = LazyFunction(_get_password_hash)

    full_name = factory.Faker("name")
    is_active = True
    is_verified = False
    role = "user"
    plan_tier = "FREE"

    # created_at / updated_at have server_default=func.now() — the DB fills
    # them on INSERT.  They'll be None until after flush() + refresh().


# ── Async DB helpers ──────────────────────────────────────────────────────────

async def create_user(db: AsyncSession, **overrides) -> User:
    """
    Persist a User to the test DB and return the refreshed instance.

    Uses flush() (not commit()) so the write stays inside the test's
    savepoint-wrapped transaction and is rolled back automatically at teardown.
    """
    user = UserFactory.build(**overrides)
    db.add(user)
    await db.flush()    # write SQL without releasing the savepoint
    await db.refresh(user)
    return user


async def create_admin(db: AsyncSession, **overrides) -> User:
    """Convenience wrapper: persist an admin user."""
    defaults = {"role": "admin", "is_verified": True}
    defaults.update(overrides)
    return await create_user(db, **defaults)

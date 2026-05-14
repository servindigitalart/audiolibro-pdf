"""
Test Configuration
==================
Global fixtures, schema lifecycle, and test infrastructure.

Architecture
------------
- Redis   : replaced by _FakeRedis (dict-backed) via autouse monkeypatch.
- Database: sonoro_test PostgreSQL DB.
            Schema is created ONCE per pytest session (pytest_configure /
            pytest_unconfigure hooks using a sync engine so no async
            event-loop gymnastics are needed at session scope).
            Each test runs inside a connection-level transaction that is
            always rolled back, so service-level commits are harmless and
            no data leaks between tests.
"""

import pytest
from typing import AsyncGenerator

from httpx import AsyncClient, ASGITransport
from sqlalchemy import create_engine, event
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

import app.core.redis as _redis_module
from app.db import models as _models  # noqa: F401 — registers every ORM model
from app.db.session import Base, get_db
from app.main import app
from app.core.config import settings


# ── URL helpers ───────────────────────────────────────────────────────────────

def _test_async_url() -> str:
    base = str(settings.database_async_url).rsplit("/", 1)[0]
    return f"{base}/sonoro_test"


def _test_sync_url() -> str:
    return _test_async_url().replace("postgresql+asyncpg://", "postgresql://")


# NullPool: no connection reuse across tests — each connect() is fresh.
# This avoids "Future attached to a different loop" errors when pytest-asyncio
# creates a new event loop per test.
_async_engine = create_async_engine(_test_async_url(), echo=False, poolclass=NullPool)


# ── Schema lifecycle (sync, runs once per pytest session) ─────────────────────

def pytest_configure(config: pytest.Config) -> None:
    """
    Create every ORM table in sonoro_test before any test runs.

    If PostgreSQL is unreachable (e.g. running only unit tests locally
    without Docker), we warn instead of crashing.  DB-dependent fixtures
    (db_session, client) will then fail individually at the test level
    rather than aborting the entire session, which lets unit tests pass.
    """
    engine = create_engine(_test_sync_url(), echo=False)
    try:
        Base.metadata.create_all(engine)
    except Exception as exc:
        import warnings
        warnings.warn(
            f"\n[conftest] Could not reach test database at {_test_sync_url()!r}.\n"
            f"  → Integration/DB tests will fail; unit tests will still run.\n"
            f"  → Error: {exc}",
            stacklevel=1,
        )
    finally:
        engine.dispose()


def pytest_unconfigure(config: pytest.Config) -> None:
    """Drop all tables after the test session completes (best-effort)."""
    engine = create_engine(_test_sync_url(), echo=False)
    try:
        Base.metadata.drop_all(engine)
    except Exception:
        pass  # DB may have been unavailable the whole session
    finally:
        engine.dispose()


# ── In-memory Redis substitute ────────────────────────────────────────────────

class _FakeRedis:
    """
    Dict-backed drop-in for redis.asyncio.Redis.
    Covers all operations used by AuthService, health router,
    RateLimitService, and AbuseDetector.
    A fresh instance is injected before every test; no cross-test state.
    """

    def __init__(self) -> None:
        self._store: dict[str, str] = {}
        self._zsets: dict[str, dict[str, float]] = {}

    # ── String ops ────────────────────────────────────────────────────────────

    async def set(self, key: str, value: str) -> None:
        self._store[key] = str(value)

    async def setex(self, key: str, expire: int, value: str) -> None:
        self._store[key] = str(value)

    async def get(self, key: str) -> str | None:
        return self._store.get(key)

    async def incr(self, key: str) -> int:
        current = int(self._store.get(key, "0"))
        self._store[key] = str(current + 1)
        return current + 1

    async def delete(self, *keys: str) -> int:
        removed = 0
        for k in keys:
            if k in self._store:
                del self._store[k]
                removed += 1
            if k in self._zsets:
                del self._zsets[k]
                removed += 1
        return removed

    # ── Sorted-set ops ────────────────────────────────────────────────────────

    async def zadd(self, key: str, mapping: dict[str, float]) -> int:
        if key not in self._zsets:
            self._zsets[key] = {}
        added = sum(1 for m in mapping if m not in self._zsets[key])
        self._zsets[key].update(mapping)
        return added

    async def zcard(self, key: str) -> int:
        return len(self._zsets.get(key, {}))

    async def zrange(
        self, key: str, start: int, stop: int, withscores: bool = False
    ) -> list:
        ordered = sorted(self._zsets.get(key, {}).items(), key=lambda x: x[1])
        end = None if stop == -1 else stop + 1
        sliced = ordered[start:end]
        return [(m, s) for m, s in sliced] if withscores else [m for m, _ in sliced]

    async def zremrangebyscore(
        self, key: str, min_score: float, max_score: float
    ) -> int:
        if key not in self._zsets:
            return 0
        to_remove = [m for m, s in self._zsets[key].items() if min_score <= s <= max_score]
        for m in to_remove:
            del self._zsets[key][m]
        return len(to_remove)

    # ── TTL / connection ──────────────────────────────────────────────────────

    async def expire(self, key: str, seconds: int) -> bool:
        return True

    async def ping(self) -> bool:
        return True

    async def close(self) -> None:
        pass


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def mock_redis(monkeypatch: pytest.MonkeyPatch) -> _FakeRedis:
    """
    Replace the module-level Redis singleton with a fresh _FakeRedis before
    every test. Because get_redis() reads _redis_client at call time (it's a
    plain global read, not a closure), patching the module attribute is the
    only thing needed — no import-side-effect tricks required.

    monkeypatch automatically restores the original value after each test.
    """
    fake = _FakeRedis()
    monkeypatch.setattr(_redis_module, "_redis_client", fake)
    return fake


@pytest.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    """
    Per-test async database session backed by a transaction that is always
    rolled back, giving each test a clean slate without recreating the schema.

    Savepoint recipe (SQLAlchemy 2.0):
    ┌─ connection ──────────────────────────────────────────────┐
    │  BEGIN  (outer transaction T)                             │
    │  SAVEPOINT s0  (absorbs the first service-level commit)   │
    │    test body runs …                                       │
    │    service calls session.commit() → RELEASE SAVEPOINT s0  │
    │    event handler immediately issues SAVEPOINT s1          │
    │    … more commits → s2, s3 …                              │
    │  ROLLBACK  (drops T and every savepoint with it)          │
    └───────────────────────────────────────────────────────────┘
    """
    async with _async_engine.connect() as conn:
        await conn.begin()           # outer transaction — never committed
        await conn.begin_nested()    # initial SAVEPOINT

        session = AsyncSession(bind=conn, expire_on_commit=False)

        # After each savepoint is released (service commit), restart a new one
        # so subsequent commits within the same test are also intercepted.
        @event.listens_for(session.sync_session, "after_transaction_end")
        def _restart_savepoint(sess, txn) -> None:
            if txn.nested and not txn._parent.nested:
                sess.expire_all()
                conn.sync_connection.begin_nested()

        yield session

        await session.close()
        await conn.rollback()   # rolls back T → zero data persists


@pytest.fixture
async def client(db_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    """
    AsyncClient pointing at the FastAPI app with:
    - get_db overridden to yield the isolated test session
    - No lifespan: init_redis / init_db are skipped entirely
      (Redis is mocked globally; DB setup happens via pytest_configure)
    """
    async def _override_get_db() -> AsyncGenerator[AsyncSession, None]:
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as ac:
        yield ac

    app.dependency_overrides.clear()

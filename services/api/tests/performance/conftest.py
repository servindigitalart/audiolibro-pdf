"""
Performance Test Fixtures
==========================
Provides:
  perf_engine           — function-scoped NullPool async engine (no loop binding)
  perf_session_factory  — async session factory backed by perf_engine
  load_test_users       — 50 pre-hashed users available for auth load tests
  instrumented_redis    — InstrumentedRedis replacing the module-level client
  perf_client           — AsyncClient wired to test DB + instrumented Redis
  report_collector      — session-scoped list; tests append RunReports to it;
                          a final summary is printed at session end

Design note — event-loop isolation
-----------------------------------
pytest-asyncio (asyncio_mode=auto) gives each *test function* its own event
loop.  asyncpg connections are bound to the loop where they were created.
Using a session-scoped pooled engine causes "Future attached to a different
loop" errors when the pool's connections (created in loop A) are reused by a
test running on loop B.

Fix: every fixture that touches asyncpg uses either:
  (a) NullPool  — no persistent connections; each acquire creates+destroys
      a fresh connection on the current running loop, or
  (b) a self-contained asyncio.run() with its own disposable engine
      (used only in load_test_users setup/teardown).
"""
from __future__ import annotations

import asyncio
import uuid
from typing import AsyncGenerator

import pytest
from httpx import AsyncClient, ASGITransport
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from contextlib import asynccontextmanager
from sqlalchemy.pool import NullPool

import app.core.redis as _redis_module
import app.routers.health as _health_module
from app.core.config import settings
from app.core.security import hash_password
from app.db.session import get_db
from app.db.models.user import User
from app.main import app
from tests.performance.instrumentation import InstrumentedRedis
from tests.performance.load_runner import RunReport
from tests.performance.report import print_report


# ── Helpers ───────────────────────────────────────────────────────────────────

class _StubConnection:
    """No-op async DB connection for health endpoint performance tests."""
    async def execute(self, *args, **kwargs):
        pass


class _StubEngine:
    """
    Minimal async engine stub for performance tests.

    The health endpoint calls `async with engine.connect() as conn: conn.execute(...)`.
    A real pooled engine would saturate PostgreSQL's max_connections at c=200.
    A stub returns instantly — we're testing HTTP throughput, not DB connectivity.
    """
    @asynccontextmanager
    async def connect(self):
        yield _StubConnection()


_stub_engine = _StubEngine()


def _test_async_url() -> str:
    base = str(settings.database_async_url).rsplit("/", 1)[0]
    return f"{base}/sonoro_test"


# ── Function-scoped: engine + session factory ─────────────────────────────────

@pytest.fixture
def perf_engine():
    """
    NullPool async engine.  Every call to session_factory creates a brand-new
    asyncpg connection on the *currently running* event loop — no stale pool
    entries from a previous loop.

    Tests in test_db_pool.py that need real pool behaviour create their own
    engines inline rather than depending on this fixture.
    """
    engine = create_async_engine(_test_async_url(), poolclass=NullPool, echo=False)
    yield engine
    asyncio.run(engine.dispose())


@pytest.fixture
def perf_session_factory(perf_engine):
    return async_sessionmaker(
        perf_engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )


# ── Session-scoped: pre-created test users ────────────────────────────────────

_PERF_USER_PASSWORD = "PerfLoad1!"
_PERF_USER_PREFIX = "perf_"


@pytest.fixture(scope="session")
def load_test_users():
    """
    Create 50 test users directly in the DB before any performance test runs.
    All have the same password (_PERF_USER_PASSWORD) so login requests are
    deterministic.  Deleted from the DB when the session ends.

    Uses a fresh NullPool engine inside each asyncio.run() call so that
    asyncpg connections are never shared across event loops.

    Returns a list of dicts: [{email, password}, ...]
    """
    users = [
        {
            "email": f"{_PERF_USER_PREFIX}{i}_{uuid.uuid4().hex[:8]}@perf.test",
            "password": _PERF_USER_PASSWORD,
        }
        for i in range(50)
    ]
    hashed = hash_password(_PERF_USER_PASSWORD)

    async def _create() -> None:
        engine = create_async_engine(_test_async_url(), poolclass=NullPool, echo=False)
        try:
            factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
            async with factory() as session:
                for u in users:
                    session.add(User(
                        email=u["email"],
                        hashed_password=hashed,
                        is_active=True,
                        is_verified=True,
                    ))
                await session.commit()
        finally:
            await engine.dispose()

    async def _cleanup() -> None:
        engine = create_async_engine(_test_async_url(), poolclass=NullPool, echo=False)
        try:
            factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
            async with factory() as session:
                await session.execute(
                    delete(User).where(User.email.like(f"{_PERF_USER_PREFIX}%@perf.test"))
                )
                await session.commit()
        finally:
            await engine.dispose()

    asyncio.run(_create())
    yield users
    asyncio.run(_cleanup())


# ── Session-scoped: report collector ─────────────────────────────────────────

@pytest.fixture(scope="session")
def report_collector():
    """
    Accumulate RunReports across all performance tests.
    Prints a combined summary after the last test in the session.
    """
    reports: list[RunReport] = []
    yield reports
    if reports:
        print_report(reports, title="COMBINED PERFORMANCE REPORT")


# ── Function-scoped: instrumented Redis ──────────────────────────────────────

@pytest.fixture
def instrumented_redis(monkeypatch):
    """
    Replace the module-level Redis client with an InstrumentedRedis for this
    test.  The mock_redis autouse fixture (from the parent conftest) has
    already set _redis_client to a plain FakeRedis — this fixture replaces it
    with the instrumented version.  Both fixtures use monkeypatch, so both
    restore cleanly in reverse order.
    """
    redis = InstrumentedRedis()
    monkeypatch.setattr(_redis_module, "_redis_client", redis)
    return redis


# ── Function-scoped: async HTTP client with test overrides ───────────────────

@pytest.fixture
async def perf_client(
    perf_session_factory,
    instrumented_redis,
    monkeypatch,
) -> AsyncGenerator[AsyncClient, None]:
    """
    httpx.AsyncClient with:
    - ASGITransport → requests go through the full FastAPI stack in-process
    - get_db overridden to use the NullPool test engine (no loop mismatch)
    - health.engine patched to _stub_engine (no real DB connection overhead)
    - Redis overridden to InstrumentedRedis (done by instrumented_redis fixture)

    Multiple concurrent coroutines inside a single test each get their own
    fresh connection from NullPool — no stale pool entries between tests.
    """
    # health.py does `from app.db.session import engine` — a direct reference.
    # We must patch the name WHERE IT IS USED (health module namespace), not
    # where it is defined (db.session module).  Using a stub avoids PostgreSQL
    # max_connections exhaustion at c=200 — we're testing HTTP throughput, not
    # DB connectivity.
    monkeypatch.setattr(_health_module, "engine", _stub_engine)

    async def _override_get_db() -> AsyncGenerator[AsyncSession, None]:
        async with perf_session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[get_db] = _override_get_db

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        timeout=30.0,
    ) as client:
        yield client

    app.dependency_overrides.clear()


# ── Function-scoped: client WITHOUT DB (for pure Redis / logic tests) ─────────

@pytest.fixture
async def perf_client_no_db(instrumented_redis) -> AsyncGenerator[AsyncClient, None]:
    """
    AsyncClient where get_db is NOT overridden — used when the test only needs
    to exercise the Redis or pure logic layer without DB involvement.
    """
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        timeout=30.0,
    ) as client:
        yield client

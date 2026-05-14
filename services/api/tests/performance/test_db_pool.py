"""
Database Pool Saturation Tests — Task 3
========================================
Validates that the SQLAlchemy async pool behaves safely under concurrent load.

Scenarios:
  test_concurrent_reads_20        — 20 concurrent sessions reading from DB
  test_pool_exhaustion_graceful   — tiny pool (size=3 overflow=1), 20 concurrent;
                                    must not crash — must queue safely
  test_no_connection_leaks        — pool size is the same before and after load
  test_concurrent_writes_no_data_mix — concurrent writes to separate rows;
                                    no row sees another writer's data
  test_no_future_loop_error       — NullPool-style: each test function gets a
                                    fresh engine; no "Future attached to loop" errors
"""
from __future__ import annotations

import asyncio
import uuid

import pytest
from sqlalchemy import text, select, func
from sqlalchemy.exc import TimeoutError as SATimeoutError
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from app.core.config import settings
from app.db.models.user import User


pytestmark = pytest.mark.performance


def _test_async_url() -> str:
    base = str(settings.database_async_url).rsplit("/", 1)[0]
    return f"{base}/sonoro_test"


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _count_users(session: AsyncSession) -> int:
    result = await session.execute(select(func.count()).select_from(User))
    return result.scalar_one()


# ── Tests ─────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_concurrent_reads_20(perf_session_factory):
    """
    20 concurrent async sessions each execute a simple SELECT.
    All must succeed with no event-loop attachment errors.
    """
    CONCURRENCY = 20
    errors: list[Exception] = []

    async def _read(idx: int) -> None:
        try:
            async with perf_session_factory() as session:
                count = await _count_users(session)
                assert count >= 0, "count must be non-negative"
        except Exception as exc:
            errors.append(exc)

    await asyncio.gather(*[_read(i) for i in range(CONCURRENCY)])

    assert not errors, (
        f"{len(errors)} out of {CONCURRENCY} concurrent reads failed:\n"
        + "\n".join(str(e) for e in errors[:5])
    )


@pytest.mark.asyncio
async def test_pool_exhaustion_graceful():
    """
    Pool size=3 overflow=0, 20 concurrent requests → only 3 can run at once.
    The remaining 17 must queue with a pool_timeout, then succeed in order.

    Validates that the pool never raises an unhandled exception or crashes —
    it must either serve the request or raise QueuePool timeout gracefully.
    """
    tiny_engine = create_async_engine(
        _test_async_url(),
        pool_size=3,
        max_overflow=0,
        pool_timeout=5,   # 5-second wait for a free connection
        echo=False,
    )
    factory = async_sessionmaker(tiny_engine, class_=AsyncSession, expire_on_commit=False)

    CONCURRENCY = 20
    successes = 0
    timeouts = 0

    async def _query(idx: int) -> None:
        nonlocal successes, timeouts
        try:
            async with factory() as session:
                await _count_users(session)
                successes += 1
        except SATimeoutError:
            timeouts += 1
        except Exception as exc:
            # Any other exception is a hard failure
            pytest.fail(f"Unexpected exception from pool: {type(exc).__name__}: {exc}")

    await asyncio.gather(*[_query(i) for i in range(CONCURRENCY)])
    await tiny_engine.dispose()

    # All requests must resolve one way or another — no hanging
    resolved = successes + timeouts
    assert resolved == CONCURRENCY, (
        f"Only {resolved}/{CONCURRENCY} requests resolved — possible deadlock"
    )
    # At least the pool-size count must succeed before any timeout can fire
    assert successes >= 3, (
        f"Expected at least 3 successes (pool_size) but got {successes}"
    )

    print(
        f"\n  Pool exhaustion: {successes} succeeded, {timeouts} timed out "
        f"(pool_size=3, concurrency=20)"
    )


@pytest.mark.asyncio
async def test_no_connection_leaks():
    """
    After a load run, a pooled engine must not hold open connections.
    Checked by comparing pool.checkedout() before and after.

    Creates its own local pooled engine so it runs on the current event loop —
    avoiding the "Future attached to a different loop" errors that arise when a
    session-scoped pooled engine is reused across test event loops.
    """
    local_engine = create_async_engine(
        _test_async_url(),
        pool_size=20,
        max_overflow=10,
        pool_pre_ping=True,
        pool_timeout=10,
        echo=False,
    )
    factory = async_sessionmaker(local_engine, class_=AsyncSession, expire_on_commit=False)

    try:
        pool = local_engine.sync_engine.pool
        before = pool.checkedout()

        CONCURRENCY = 30
        errors: list[Exception] = []

        async def _use_session(_: int) -> None:
            try:
                async with factory() as session:
                    await _count_users(session)
            except Exception as exc:
                errors.append(exc)

        await asyncio.gather(*[_use_session(i) for i in range(CONCURRENCY)])

        after = pool.checkedout()

        assert not errors, f"{len(errors)} sessions raised errors"
        assert after == before, (
            f"Connection leak detected: {before} checked out before, "
            f"{after} after — {after - before} connections not returned to pool"
        )
    finally:
        await local_engine.dispose()


@pytest.mark.asyncio
async def test_concurrent_writes_no_data_mix(perf_session_factory):
    """
    30 concurrent transactions each create a unique user and immediately read
    it back within the same session.  Each transaction must see only its own
    data — no write from another session leaks through.

    Uses a unique email prefix per coroutine so rows are unambiguously owned.
    Cleans up all created rows after the test.
    """
    CONCURRENCY = 30
    prefix = f"dbpool_test_{uuid.uuid4().hex[:6]}"
    created_emails: list[str] = []
    errors: list[str] = []

    async def _write_and_verify(idx: int) -> None:
        email = f"{prefix}_{idx}@pool.test"
        try:
            async with perf_session_factory() as session:
                # Create
                user = User(
                    email=email,
                    hashed_password="$2b$12$fakehash",
                    is_active=True,
                    is_verified=True,
                )
                session.add(user)
                await session.flush()  # assign PK without committing

                # Read back within the same transaction
                result = await session.execute(
                    select(User).where(User.email == email)
                )
                fetched = result.scalar_one_or_none()

                assert fetched is not None, f"Row {email} not visible in own transaction"
                assert fetched.email == email, "Wrong row returned"

                await session.commit()
                created_emails.append(email)
        except Exception as exc:
            errors.append(f"idx={idx}: {type(exc).__name__}: {exc}")

    await asyncio.gather(*[_write_and_verify(i) for i in range(CONCURRENCY)])

    # Cleanup
    if created_emails:
        async with perf_session_factory() as session:
            for email in created_emails:
                result = await session.execute(select(User).where(User.email == email))
                user = result.scalar_one_or_none()
                if user:
                    await session.delete(user)
            await session.commit()

    assert not errors, (
        f"{len(errors)} concurrent writes failed:\n" + "\n".join(errors[:5])
    )
    assert len(created_emails) == CONCURRENCY, (
        f"Only {len(created_emails)}/{CONCURRENCY} rows committed"
    )


@pytest.mark.asyncio
async def test_nullpool_no_future_loop_error():
    """
    Regression guard: NullPool engines must not produce
    'Future attached to a different loop' errors across multiple awaits.

    Creates a NullPool engine and fires 10 sequential coroutines.
    Each coroutine gets a fresh connection (NullPool guarantee).
    """
    engine = create_async_engine(_test_async_url(), poolclass=NullPool, echo=False)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    errors: list[Exception] = []

    for _ in range(10):
        try:
            async with factory() as session:
                await session.execute(text("SELECT 1"))
        except Exception as exc:
            errors.append(exc)

    await engine.dispose()

    assert not errors, (
        "NullPool engine raised errors across sequential awaits:\n"
        + "\n".join(str(e) for e in errors)
    )

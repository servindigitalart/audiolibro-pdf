"""
Chaos Injection Framework
==========================
Failure injection primitives for financial resilience testing.

Design principles:
  - All failures are DETERMINISTIC — configured explicitly, never random
  - FailingRedis wraps FakeRedis; adds 4 injectable failure modes
  - SessionPatcher patches AsyncSession methods inline; restores on exit
  - ChaosOrchestrator coordinates multi-component simultaneous failures
  - Every injector is reversible (no permanent state mutation)

Failure Modes
-------------
HARD_FAIL     — Exception immediately, NO state change (clean failure)
PARTIAL_WRITE — State IS changed, THEN exception raised (network drop after write)
TIMEOUT       — asyncio.TimeoutError, no state change (hung connection)
SILENT_DROP   — Call accepted, data silently lost, returns plausible zero value

The PARTIAL_WRITE mode is the most dangerous for financial correctness:
  - Redis processed the increment server-side
  - The TCP response was dropped (client never confirmed the write)
  - On retry, the value is double-counted
  This mode specifically tests recovery paths.
"""
from __future__ import annotations

import asyncio
import contextlib
from enum import Enum
from typing import Any, Callable, Awaitable, Iterator

from tests.fakes import FakeRedis, FakePipeline


# ── Failure modes ─────────────────────────────────────────────────────────────

class FailureMode(str, Enum):
    HARD_FAIL     = "hard_fail"   # Exception immediately; no state change
    PARTIAL_WRITE = "partial"     # State written; exception on return
    TIMEOUT       = "timeout"     # asyncio.TimeoutError; no state change
    SILENT_DROP   = "silent"      # Accepted; data lost; plausible zero returned


# ── FailingRedis ──────────────────────────────────────────────────────────────

class FailingRedis(FakeRedis):
    """
    FakeRedis with injectable failure configuration.

    Usage:
        redis = FailingRedis()
        redis.configure(fail_ops=["pipeline"], mode=FailureMode.HARD_FAIL)
        await svc.record(user_id, api_calls=1)  # pipeline raises ConnectionError

    After each test, call redis.clear_failures() or create a new instance.
    """

    def __init__(self) -> None:
        super().__init__()
        self._failing_ops: set[str] = set()
        self._mode: FailureMode = FailureMode.HARD_FAIL
        self._fail_after: int = -1   # -1 = always; N = fail after N successes
        self._op_counters: dict[str, int] = {}

    # ── Configuration ─────────────────────────────────────────────────────────

    def configure(
        self,
        fail_ops: list[str],
        mode: FailureMode = FailureMode.HARD_FAIL,
        after: int = -1,
    ) -> "FailingRedis":
        """Configure failure injection. Returns self for method chaining."""
        self._failing_ops = set(fail_ops)
        self._mode = mode
        self._fail_after = after
        self._op_counters.clear()
        return self

    def clear_failures(self) -> "FailingRedis":
        """Remove all failure configuration — Redis behaves normally again."""
        self._failing_ops.clear()
        self._op_counters.clear()
        return self

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _should_fail(self, op: str) -> bool:
        if op not in self._failing_ops:
            return False
        count = self._op_counters.get(op, 0) + 1
        self._op_counters[op] = count
        # -1 = always fail; 0 = fail on first call; N = fail after N successes
        return self._fail_after == -1 or count > self._fail_after

    def _raise(self, op: str) -> None:
        if self._mode == FailureMode.TIMEOUT:
            raise asyncio.TimeoutError(f"Redis: {op} timed out (chaos)")
        raise ConnectionError(f"Redis: {op} connection lost (chaos)")

    # ── Instrumented operations ───────────────────────────────────────────────

    async def hincrbyfloat(self, key: str, field: str, amount: float) -> float:
        if self._should_fail("hincrbyfloat"):
            if self._mode == FailureMode.PARTIAL_WRITE:
                result = await super().hincrbyfloat(key, field, amount)
                raise ConnectionError("Redis: hincrbyfloat response lost — partial write")
            if self._mode == FailureMode.SILENT_DROP:
                return 0.0
            self._raise("hincrbyfloat")
        return await super().hincrbyfloat(key, field, amount)

    async def hincrby(self, key: str, field: str, amount: int) -> int:
        if self._should_fail("hincrby"):
            if self._mode == FailureMode.PARTIAL_WRITE:
                result = await super().hincrby(key, field, amount)
                raise ConnectionError("Redis: hincrby response lost — partial write")
            if self._mode == FailureMode.SILENT_DROP:
                return 0
            self._raise("hincrby")
        return await super().hincrby(key, field, amount)

    async def hgetall(self, key: str) -> dict[str, str]:
        if self._should_fail("hgetall"):
            if self._mode == FailureMode.SILENT_DROP:
                return {}
            self._raise("hgetall")
        return await super().hgetall(key)

    async def get(self, key: str) -> str | None:
        if self._should_fail("get"):
            if self._mode == FailureMode.SILENT_DROP:
                return None
            self._raise("get")
        return await super().get(key)

    async def set(self, key: str, value: str) -> None:
        if self._should_fail("set"):
            if self._mode == FailureMode.PARTIAL_WRITE:
                await super().set(key, value)
                raise ConnectionError("Redis: set response lost — partial write")
            if self._mode == FailureMode.SILENT_DROP:
                return
            self._raise("set")
        return await super().set(key, value)

    def pipeline(self, transaction: bool = True) -> "FailingPipeline":
        if self._should_fail("pipeline"):
            if self._mode not in (FailureMode.PARTIAL_WRITE, FailureMode.SILENT_DROP):
                self._raise("pipeline")
        return FailingPipeline(self)


# ── FailingPipeline ───────────────────────────────────────────────────────────

class FailingPipeline(FakePipeline):
    """
    Pipeline that fails during execute() based on FailingRedis configuration.

    PARTIAL_WRITE mode: executes the first half of queued commands, then raises.
    This models a Redis pipeline where the TCP connection drops mid-transmission.
    """

    def __init__(self, redis: FailingRedis) -> None:
        super().__init__(redis)
        self._chaos_redis = redis

    async def execute(self) -> list:
        fr = self._chaos_redis
        if not fr._should_fail("pipeline_execute"):
            return await super().execute()

        mode = fr._mode
        if mode == FailureMode.SILENT_DROP:
            self._queue.clear()
            return []

        if mode == FailureMode.PARTIAL_WRITE:
            # Execute the first half of commands — data IS partially written
            half = len(self._queue) // 2
            results = []
            for cmd, *args in self._queue[:half]:
                fn = getattr(fr, cmd)
                results.append(await fn(*args))
            self._queue.clear()
            raise ConnectionError(
                f"Redis: pipeline partially executed ({half} of {len(results)+half} "
                "commands written — network drop mid-pipeline)"
            )

        if mode == FailureMode.TIMEOUT:
            self._queue.clear()
            raise asyncio.TimeoutError("Redis: pipeline execute timed out (chaos)")

        self._queue.clear()
        raise ConnectionError("Redis: pipeline execute failed (chaos)")


# ── Session failure injection ─────────────────────────────────────────────────

@contextlib.asynccontextmanager
async def inject_commit_failure(session, after: int = 0):
    """
    Context manager: patches session.commit() to raise after `after` successes.

    after=0 → fails on the FIRST commit
    after=1 → first commit succeeds, second fails
    after=N → first N commits succeed, then fail

    The session is restored after the context exits regardless of outcome.
    The raised exception is RuntimeError (simulates OS-level connection drop,
    not a SQL constraint violation — tests that the service handles unexpected
    DB outages, not expected IntegrityErrors).
    """
    count = 0
    original_commit = session.commit

    async def _failing_commit():
        nonlocal count
        count += 1
        if count > after:
            raise RuntimeError(
                f"CHAOS: injected DB commit failure (call #{count}, threshold={after})"
            )
        return await original_commit()

    session.commit = _failing_commit
    try:
        yield session
    finally:
        session.commit = original_commit


@contextlib.asynccontextmanager
async def inject_execute_failure(session, after: int = 0):
    """
    Context manager: patches session.execute() to raise after `after` successes.

    Models: DB query timeout / network partition mid-transaction.
    """
    count = 0
    original_execute = session.execute

    async def _failing_execute(*args, **kwargs):
        nonlocal count
        count += 1
        if count > after:
            raise RuntimeError(
                f"CHAOS: injected DB execute failure (call #{count}, threshold={after})"
            )
        return await original_execute(*args, **kwargs)

    session.execute = _failing_execute
    try:
        yield session
    finally:
        session.execute = original_execute


# ── ChaosOrchestrator ─────────────────────────────────────────────────────────

class ChaosOrchestrator:
    """
    Coordinates simultaneous multi-component failures.

    Models real production scenarios where Redis AND the DB degrade together
    (e.g., a network partition isolating the app from both data stores).

    Usage:
        chaos = ChaosOrchestrator(redis=failing_redis, session=db_session)
        async with chaos.both_down():
            result = await service.do_something()  # both fail
        # After context: both restored
    """

    def __init__(self, redis: FailingRedis, session) -> None:
        self._redis = redis
        self._session = session

    @contextlib.asynccontextmanager
    async def redis_hard_down(self, ops: list[str] | None = None):
        """Redis raises ConnectionError for specified ops (or all pipeline ops)."""
        target_ops = ops or ["pipeline", "pipeline_execute", "hgetall", "get", "set"]
        self._redis.configure(fail_ops=target_ops, mode=FailureMode.HARD_FAIL)
        try:
            yield
        finally:
            self._redis.clear_failures()

    @contextlib.asynccontextmanager
    async def redis_partial_write(self, ops: list[str] | None = None):
        """Redis accepts writes but drops responses — partial write scenario."""
        target_ops = ops or ["pipeline_execute", "hincrbyfloat", "hincrby"]
        self._redis.configure(fail_ops=target_ops, mode=FailureMode.PARTIAL_WRITE)
        try:
            yield
        finally:
            self._redis.clear_failures()

    @contextlib.asynccontextmanager
    async def db_commit_fails(self, after: int = 0):
        """DB commit fails — simulates connection drop after write."""
        async with inject_commit_failure(self._session, after=after):
            yield

    @contextlib.asynccontextmanager
    async def both_hard_down(self):
        """Both Redis and DB fail simultaneously."""
        self._redis.configure(
            fail_ops=["pipeline", "pipeline_execute", "hgetall"],
            mode=FailureMode.HARD_FAIL,
        )
        async with inject_commit_failure(self._session, after=0):
            try:
                yield
            finally:
                self._redis.clear_failures()

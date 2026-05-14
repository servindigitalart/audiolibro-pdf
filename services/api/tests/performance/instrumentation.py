"""
Performance Instrumentation
============================
InstrumentedRedis  — FakeRedis subclass that counts every async op.
QueryCounter       — per-coroutine DB query counter via ContextVar.
CostModel          — translates op counts + latency into USD estimates.
"""
from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass, field

from tests.fakes import FakeRedis


# ── Redis instrumentation ─────────────────────────────────────────────────────

class InstrumentedRedis(FakeRedis):
    """
    FakeRedis that counts every async operation.

    Counters are plain ints — safe for asyncio (single-threaded event loop).
    Reset with .reset_counters() between logical test phases.
    """

    def __init__(self) -> None:
        super().__init__()
        self.op_count: int = 0
        self.op_breakdown: dict[str, int] = {}

    def _tick(self, op: str) -> None:
        self.op_count += 1
        self.op_breakdown[op] = self.op_breakdown.get(op, 0) + 1

    def reset_counters(self) -> None:
        self.op_count = 0
        self.op_breakdown.clear()

    # ── String ops ─────────────────────────────────────────────────────────────

    async def set(self, key, value):
        self._tick("set")
        return await super().set(key, value)

    async def setex(self, key, expire_seconds, value):
        self._tick("setex")
        return await super().setex(key, expire_seconds, value)

    async def get(self, key):
        self._tick("get")
        return await super().get(key)

    async def incr(self, key):
        self._tick("incr")
        return await super().incr(key)

    async def delete(self, *keys):
        self._tick("delete")
        return await super().delete(*keys)

    # ── Sorted-set ops ─────────────────────────────────────────────────────────

    async def zadd(self, key, mapping):
        self._tick("zadd")
        return await super().zadd(key, mapping)

    async def zcard(self, key):
        self._tick("zcard")
        return await super().zcard(key)

    async def zrange(self, key, start, stop, withscores=False):
        self._tick("zrange")
        return await super().zrange(key, start, stop, withscores=withscores)

    async def zremrangebyscore(self, key, min_score, max_score):
        self._tick("zremrangebyscore")
        return await super().zremrangebyscore(key, min_score, max_score)

    async def expire(self, key, seconds):
        self._tick("expire")
        return await super().expire(key, seconds)

    async def ping(self):
        self._tick("ping")
        return await super().ping()

    @property
    def ops_per_type(self) -> dict[str, int]:
        return dict(self.op_breakdown)


# ── DB query counting via ContextVar ──────────────────────────────────────────

# Each asyncio task (coroutine) gets its own slot — no cross-request leakage.
_query_counter: ContextVar[list[int]] = ContextVar("_query_counter", default=None)


class QueryCounter:
    """
    Context manager that counts SQLAlchemy execute() calls for the current
    async task.

    Usage inside a FastAPI dependency or test:
        async with QueryCounter() as qc:
            result = await session.execute(...)
        print(qc.count)  # number of execute() calls

    For integration with ASGI load tests (where sessions are created inside
    the app), wrap the session factory in CountingSession.
    """

    def __init__(self) -> None:
        self._counter: list[int] = [0]
        self._token = None

    async def __aenter__(self) -> "QueryCounter":
        self._token = _query_counter.set(self._counter)
        return self

    async def __aexit__(self, *_) -> None:
        if self._token is not None:
            _query_counter.reset(self._token)

    @property
    def count(self) -> int:
        return self._counter[0]

    @staticmethod
    def increment() -> None:
        """Called by CountingSession on each execute()."""
        slot = _query_counter.get(None)
        if slot is not None:
            slot[0] += 1


class CountingSession:
    """
    Thin async-session wrapper that increments QueryCounter on every execute.

    Used in performance conftest to instrument the DB sessions injected into
    the FastAPI dependency graph.
    """

    def __init__(self, session) -> None:
        self._s = session

    async def execute(self, *args, **kwargs):
        QueryCounter.increment()
        return await self._s.execute(*args, **kwargs)

    # Delegate everything else to the real session
    def __getattr__(self, name: str):
        return getattr(self._s, name)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return await self._s.__aexit__(*args)


# ── Cost model ────────────────────────────────────────────────────────────────

# Rough cost anchors (USD) calibrated against:
#   - AWS RDS db.t3.medium on-demand pricing ($0.068/hr ÷ 3600s ÷ expected QPS)
#   - ElastiCache cache.t3.micro on-demand pricing
#   - AWS Fargate 0.25 vCPU / 0.5 GB at $0.04048/vCPU-hr

DB_QUERY_USD: float = 1e-5      # $0.00001 per query  → $10 per million
REDIS_OP_USD: float = 5e-7      # $0.0000005 per op   → $0.50 per million
COMPUTE_PER_MS_USD: float = 3e-8  # $0.00000003 per ms  → $0.03 per 1000 req-seconds


@dataclass
class RequestCost:
    db_queries: int
    redis_ops: int
    latency_ms: float

    @property
    def db_usd(self) -> float:
        return self.db_queries * DB_QUERY_USD

    @property
    def redis_usd(self) -> float:
        return self.redis_ops * REDIS_OP_USD

    @property
    def compute_usd(self) -> float:
        return self.latency_ms * COMPUTE_PER_MS_USD

    @property
    def total_usd(self) -> float:
        return self.db_usd + self.redis_usd + self.compute_usd

    @property
    def monthly_usd_at_1m_rpm(self) -> float:
        """Extrapolated monthly cost if this endpoint handles 1M req/month."""
        return self.total_usd * 1_000_000

    def __repr__(self) -> str:
        return (
            f"RequestCost(db={self.db_queries}q ${self.db_usd*1e6:.2f}µ, "
            f"redis={self.redis_ops}op ${self.redis_usd*1e6:.2f}µ, "
            f"compute={self.latency_ms:.1f}ms ${self.compute_usd*1e6:.2f}µ, "
            f"total=${self.total_usd*1e6:.2f}µ)"
        )


def estimate_cost(
    db_queries: int,
    redis_ops: int,
    latency_ms: float,
) -> RequestCost:
    return RequestCost(db_queries=db_queries, redis_ops=redis_ops, latency_ms=latency_ms)

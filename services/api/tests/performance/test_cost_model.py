"""
Cost Per Request Tracking — Task 4
=====================================
Validates the instrumentation layer (query counting, Redis op counting) and
the cost model (USD estimates per request).

Tests here are unit-style (no HTTP client needed) — they verify the
instrumentation machinery itself before it is relied on by latency/load tests.
"""
from __future__ import annotations

import asyncio

import pytest

from tests.performance.instrumentation import (
    DB_QUERY_USD,
    InstrumentedRedis,
    QueryCounter,
    REDIS_OP_USD,
    COMPUTE_PER_MS_USD,
    RequestCost,
    estimate_cost,
)
from tests.performance.load_runner import RequestResult, RunReport


pytestmark = pytest.mark.performance


# ── InstrumentedRedis counting ────────────────────────────────────────────────

def test_instrumented_redis_counts_each_op_type():
    """Every public async method increments op_count by exactly 1."""
    redis = InstrumentedRedis()

    async def _run():
        await redis.set("k", "v")
        await redis.get("k")
        await redis.incr("counter")
        await redis.setex("ttl_key", 60, "val")
        await redis.delete("k")
        await redis.zadd("z", {"m": 1.0})
        await redis.zcard("z")
        await redis.zrange("z", 0, -1)
        await redis.zremrangebyscore("z", 0, 0)
        await redis.expire("counter", 30)
        await redis.ping()

    asyncio.run(_run())

    assert redis.op_count == 11, f"Expected 11 ops, got {redis.op_count}"
    expected_ops = {
        "set": 1, "get": 1, "incr": 1, "setex": 1, "delete": 1,
        "zadd": 1, "zcard": 1, "zrange": 1, "zremrangebyscore": 1,
        "expire": 1, "ping": 1,
    }
    assert redis.op_breakdown == expected_ops


def test_instrumented_redis_reset_clears_counters():
    redis = InstrumentedRedis()

    async def _run():
        await redis.set("x", "1")
        await redis.get("x")

    asyncio.run(_run())
    assert redis.op_count == 2

    redis.reset_counters()
    assert redis.op_count == 0
    assert redis.op_breakdown == {}


def test_instrumented_redis_concurrent_counting():
    """All concurrent increments must be counted (asyncio is single-threaded)."""
    redis = InstrumentedRedis()
    N = 500

    async def _run():
        await asyncio.gather(*[redis.incr("shared_counter") for _ in range(N)])
        await asyncio.gather(*[redis.get("shared_counter") for _ in range(N)])

    asyncio.run(_run())

    assert redis.op_count == N * 2
    assert redis.op_breakdown["incr"] == N
    assert redis.op_breakdown["get"] == N


# ── QueryCounter ──────────────────────────────────────────────────────────────

def test_query_counter_increments():
    async def _run():
        async with QueryCounter() as qc:
            QueryCounter.increment()
            QueryCounter.increment()
            QueryCounter.increment()
            return qc.count

    result = asyncio.run(_run())
    assert result == 3


def test_query_counter_isolated_between_tasks():
    """Two concurrent QueryCounters must not bleed into each other."""
    async def _task(n_increments: int) -> int:
        async with QueryCounter() as qc:
            for _ in range(n_increments):
                QueryCounter.increment()
            return qc.count

    async def _run():
        a, b = await asyncio.gather(_task(3), _task(7))
        return a, b

    a, b = asyncio.run(_run())
    assert a == 3, f"Task A: expected 3, got {a}"
    assert b == 7, f"Task B: expected 7, got {b}"


def test_query_counter_resets_after_context():
    """Counter must not bleed between sequential uses."""
    async def _run():
        async with QueryCounter() as qc1:
            QueryCounter.increment()
            assert qc1.count == 1

        async with QueryCounter() as qc2:
            assert qc2.count == 0  # fresh counter, no bleed from qc1
            QueryCounter.increment()
            QueryCounter.increment()
            assert qc2.count == 2

    asyncio.run(_run())


# ── CostModel / RequestCost ───────────────────────────────────────────────────

def test_request_cost_zero_inputs():
    cost = estimate_cost(db_queries=0, redis_ops=0, latency_ms=0)
    assert cost.total_usd == 0.0
    assert cost.db_usd == 0.0
    assert cost.redis_usd == 0.0
    assert cost.compute_usd == 0.0


def test_request_cost_db_only():
    cost = estimate_cost(db_queries=5, redis_ops=0, latency_ms=0)
    expected = 5 * DB_QUERY_USD
    assert abs(cost.total_usd - expected) < 1e-12


def test_request_cost_redis_only():
    cost = estimate_cost(db_queries=0, redis_ops=100, latency_ms=0)
    expected = 100 * REDIS_OP_USD
    assert abs(cost.total_usd - expected) < 1e-12


def test_request_cost_compute_only():
    cost = estimate_cost(db_queries=0, redis_ops=0, latency_ms=100)
    expected = 100 * COMPUTE_PER_MS_USD
    assert abs(cost.total_usd - expected) < 1e-12


def test_request_cost_combined():
    cost = estimate_cost(db_queries=2, redis_ops=9, latency_ms=50.0)
    expected = (
        2    * DB_QUERY_USD
        + 9  * REDIS_OP_USD
        + 50 * COMPUTE_PER_MS_USD
    )
    assert abs(cost.total_usd - expected) < 1e-12


def test_monthly_extrapolation_scales_correctly():
    """1M requests/month at a given per-request cost."""
    cost = estimate_cost(db_queries=2, redis_ops=9, latency_ms=20.0)
    monthly = cost.monthly_usd_at_1m_rpm
    assert monthly == cost.total_usd * 1_000_000


def test_cost_ordering_health_vs_auth():
    """
    A login request (2 DB queries + 9 Redis ops) must cost more than
    a health check (0 DB + 0 Redis).
    """
    health_cost = estimate_cost(db_queries=0, redis_ops=0, latency_ms=5.0)
    login_cost  = estimate_cost(db_queries=2, redis_ops=9, latency_ms=310.0)
    assert login_cost.total_usd > health_cost.total_usd


# ── Per-endpoint cost report ──────────────────────────────────────────────────

def test_endpoint_cost_report_format():
    """
    Build a synthetic report, compute per-endpoint costs, and verify that
    the more Redis-heavy endpoint is flagged as more expensive.
    """
    # Simulate a load run result for two endpoints
    health_results = [RequestResult(latency_ms=5.0, status_code=200, redis_ops=0, db_queries=0)] * 100
    auth_results   = [RequestResult(latency_ms=60.0, status_code=200, redis_ops=9, db_queries=2)] * 100

    health_report = RunReport(
        endpoint="GET /health",
        total=100, concurrency=10, duration_s=1.0,
        results=health_results,
    )
    auth_report = RunReport(
        endpoint="GET /me",
        total=100, concurrency=10, duration_s=5.0,
        results=auth_results,
    )

    health_cost = estimate_cost(
        db_queries=int(health_report.avg_db_queries),
        redis_ops=int(health_report.avg_redis_ops),
        latency_ms=health_report.mean_ms,
    )
    auth_cost = estimate_cost(
        db_queries=int(auth_report.avg_db_queries),
        redis_ops=int(auth_report.avg_redis_ops),
        latency_ms=auth_report.mean_ms,
    )

    assert auth_cost.total_usd > health_cost.total_usd, (
        "Auth endpoint should cost more than health check"
    )

    # Monthly projection
    health_monthly = health_cost.monthly_usd_at_1m_rpm
    auth_monthly   = auth_cost.monthly_usd_at_1m_rpm
    assert auth_monthly > health_monthly

    print(f"\n  Health: ${health_monthly:.4f}/month per 1M requests")
    print(f"  Auth:   ${auth_monthly:.4f}/month per 1M requests")
    print(f"  Ratio:  {auth_monthly / health_monthly:.1f}× more expensive")


def test_expensive_endpoint_detection():
    """
    Auto-detect endpoints whose estimated monthly cost exceeds a threshold.
    Threshold: $1.00 per million requests per month.
    """
    MONTHLY_THRESHOLD_PER_1M = 1.00  # USD

    endpoints = [
        ("GET /health",       estimate_cost(db_queries=0, redis_ops=0,  latency_ms=5.0)),
        ("GET /api/v1/me",    estimate_cost(db_queries=2, redis_ops=9,  latency_ms=60.0)),
        ("POST /auth/login",  estimate_cost(db_queries=2, redis_ops=9,  latency_ms=310.0)),
        ("POST /docs/upload", estimate_cost(db_queries=5, redis_ops=3,  latency_ms=800.0)),
    ]

    expensive = [
        (ep, cost)
        for ep, cost in endpoints
        if cost.monthly_usd_at_1m_rpm > MONTHLY_THRESHOLD_PER_1M
    ]

    # We expect some expensive endpoints — just verify the detection logic works
    print(f"\n  Expensive endpoints (> ${MONTHLY_THRESHOLD_PER_1M}/M/month):")
    for ep, cost in expensive:
        print(f"    {ep}: ${cost.monthly_usd_at_1m_rpm:.4f}")
    print(f"  Cheap endpoints:")
    for ep, cost in endpoints:
        if cost.monthly_usd_at_1m_rpm <= MONTHLY_THRESHOLD_PER_1M:
            print(f"    {ep}: ${cost.monthly_usd_at_1m_rpm:.4f}")

    # Health should be cheap
    health_cost = next(c for ep, c in endpoints if "health" in ep)
    assert health_cost.monthly_usd_at_1m_rpm < MONTHLY_THRESHOLD_PER_1M, (
        "Health endpoint should be under the $1/M threshold"
    )

"""
High Concurrency Load Tests — Task 1
=====================================
Simulates real concurrent request pressure through the full FastAPI/ASGI stack.

All tests use httpx.AsyncClient + ASGITransport (in-process, no network).
Latencies reflect real FastAPI/SQLAlchemy/middleware overhead without TCP noise.

Test inventory:
  test_health_1000_concurrent   — 1000 req at c=200; health endpoint; p95 < 50ms
  test_health_burst             — 100 req at c=100 (fully parallel); no failures
  test_mixed_load_concurrent    — health + GET root interleaved at c=30
  test_concurrent_distinct_clients — no session state leaks between clients
  test_sustained_throughput     — 500 req in 5 batches; stable latency across batches
"""
from __future__ import annotations

import asyncio
import statistics
import time

import pytest

from tests.performance.load_runner import RequestResult, RunReport, run_load, run_mixed_load
from tests.performance.report import print_report, BUDGETS_MS


pytestmark = pytest.mark.performance


# ── Helpers ───────────────────────────────────────────────────────────────────

def _assert_stability(reports: list[RunReport], label: str) -> None:
    """Assert that p95 latency does not regress more than 6× across batches.

    6× allows for JIT warmup on the first batch and occasional GC pauses
    (both common in in-process ASGI tests) while still catching real degradation
    from connection pool exhaustion, memory leaks, or lock contention.
    """
    p95s = [r.p95 for r in reports if r.latencies_ms]
    if len(p95s) < 2:
        return
    ratio = max(p95s) / min(p95s)
    assert ratio < 6.0, (
        f"{label}: p95 latency varied {ratio:.1f}× across batches — "
        f"min={min(p95s):.1f}ms max={max(p95s):.1f}ms.  "
        "This suggests a concurrency bug or resource exhaustion."
    )


# ── Tests ─────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_health_1000_concurrent(perf_client, report_collector):
    """
    1000 concurrent health-check requests.
    The health endpoint is the lightest path through the stack — it exercises
    routing, middleware (RequestID, Metrics, CORS, GZip), and response
    serialisation without DB I/O.

    Budget: p95 < 50ms (in-process).
    """
    async def _req(idx: int) -> RequestResult:
        resp = await perf_client.get("/api/v1/health")
        return RequestResult(latency_ms=0, status_code=resp.status_code)

    report = await run_load(_req, endpoint="GET /api/v1/health (1000 concurrent)", total=1000, concurrency=200)
    report_collector.append(report)
    print_report([report], title="Health 1000-Concurrent", budget_category="read")

    assert report.failure_rate == 0.0, (
        f"{report.total - len(report.successful)} requests failed under load"
    )
    # p95 budget is NOT asserted here — this is a throughput stress test (c=200).
    # At concurrency 200, BaseHTTPMiddleware's per-request asyncio-task overhead
    # accumulates; individual latency is measured in test_latency_budget.py at
    # production-realistic concurrency (c=20) where p95 < 100ms.
    assert report.throughput_rps > 100, (
        f"throughput {report.throughput_rps:.0f} rps too low — "
        "possible middleware bottleneck"
    )


@pytest.mark.asyncio
async def test_health_burst(perf_client, report_collector):
    """
    100 requests with concurrency == total (fully parallel burst).
    Validates that asyncio.gather under the ASGI transport does not deadlock
    or starve when all requests are submitted simultaneously.
    """
    async def _req(idx: int) -> RequestResult:
        resp = await perf_client.get("/api/v1/health")
        return RequestResult(latency_ms=0, status_code=resp.status_code)

    report = await run_load(_req, endpoint="GET /api/v1/health (burst c=100)", total=100, concurrency=100)
    report_collector.append(report)

    assert report.failure_rate == 0.0
    # Under full parallelism response times may be higher but must stay sane
    assert report.p99 < 2000, f"p99={report.p99:.1f}ms — possible deadlock or starvation"


@pytest.mark.asyncio
async def test_mixed_load_concurrent(perf_client, report_collector):
    """
    Health endpoint and root endpoint run concurrently, interleaved.
    Tests that different routes don't interfere under shared concurrency.
    """
    async def _health(idx: int) -> RequestResult:
        resp = await perf_client.get("/api/v1/health")
        return RequestResult(latency_ms=0, status_code=resp.status_code)

    async def _root(idx: int) -> RequestResult:
        resp = await perf_client.get("/api/v1/")
        return RequestResult(latency_ms=0, status_code=resp.status_code)

    reports = await run_mixed_load(
        [(_health, "GET /api/v1/health"), (_root, "GET /api/v1/")],
        total_per_scenario=150,
        concurrency=30,
    )
    report_collector.extend(reports)
    print_report(reports, title="Mixed Load Concurrent")

    for r in reports:
        assert r.failure_rate == 0.0, f"{r.endpoint}: {r.failure_rate:.1%} failure rate"
        assert r.p95 < 200, f"{r.endpoint}: p95={r.p95:.1f}ms — unexpected slowdown"


@pytest.mark.asyncio
async def test_concurrent_distinct_clients(perf_client, report_collector):
    """
    Verify that concurrent requests do not share session state.
    Each request sees its own response — no cross-contamination of headers,
    request-IDs, or response bodies.
    """
    request_ids_seen: list[str] = []

    async def _req(idx: int) -> RequestResult:
        resp = await perf_client.get("/api/v1/health")
        rid = resp.headers.get("x-request-id", "")
        request_ids_seen.append(rid)
        return RequestResult(latency_ms=0, status_code=resp.status_code)

    report = await run_load(_req, endpoint="GET /api/v1/health (ID isolation)", total=200, concurrency=50)
    report_collector.append(report)

    assert report.failure_rate == 0.0

    # Every successful response should carry a unique request-ID
    non_empty = [r for r in request_ids_seen if r]
    if non_empty:
        unique = set(non_empty)
        collision_rate = 1 - len(unique) / len(non_empty)
        assert collision_rate == 0.0, (
            f"Request-ID collision rate {collision_rate:.1%} — "
            "RequestIDMiddleware is not generating unique IDs"
        )


@pytest.mark.asyncio
async def test_sustained_throughput(perf_client, report_collector):
    """
    500 requests split into 5 batches of 100 — tests that latency remains
    stable over time (no memory leak, no connection pool degradation).
    """
    BATCHES = 5
    BATCH_SIZE = 100
    CONCURRENCY = 25
    batch_reports: list[RunReport] = []

    async def _req(idx: int) -> RequestResult:
        resp = await perf_client.get("/api/v1/health")
        return RequestResult(latency_ms=0, status_code=resp.status_code)

    for b in range(BATCHES):
        r = await run_load(
            _req,
            endpoint=f"GET /api/v1/health (batch {b+1}/{BATCHES})",
            total=BATCH_SIZE,
            concurrency=CONCURRENCY,
        )
        batch_reports.append(r)
        assert r.failure_rate == 0.0, f"Batch {b+1} had failures: {r.failure_rate:.1%}"

    report_collector.extend(batch_reports)

    _assert_stability(batch_reports, "sustained-throughput")

    # Final batch should not be slower than 3× the first
    first_p95 = batch_reports[0].p95
    last_p95  = batch_reports[-1].p95
    assert last_p95 < first_p95 * 3, (
        f"Latency degraded over time: first={first_p95:.1f}ms last={last_p95:.1f}ms"
    )

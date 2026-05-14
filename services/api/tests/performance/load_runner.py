"""
Load Runner
===========
Core async concurrency engine.  Executes N requests at C concurrency and
returns a RunReport with percentile latencies, throughput, and op counts.
"""
from __future__ import annotations

import asyncio
import statistics
import time
from dataclasses import dataclass, field
from typing import Awaitable, Callable, Optional


# ── Result types ──────────────────────────────────────────────────────────────

@dataclass
class RequestResult:
    """Outcome of a single request."""
    latency_ms: float
    status_code: int
    error: Optional[str] = None
    db_queries: int = 0
    redis_ops: int = 0


@dataclass
class RunReport:
    """
    Aggregated statistics for one load run.

    Attributes:
        endpoint   : label for the operation (URL or description)
        total      : number of requests attempted
        concurrency: maximum inflight at any moment
        duration_s : wall-clock time for the entire run
        results    : raw per-request outcomes
    """
    endpoint: str
    total: int
    concurrency: int
    duration_s: float
    results: list[RequestResult]

    # ── Derived views ──────────────────────────────────────────────────────────

    @property
    def successful(self) -> list[RequestResult]:
        return [r for r in self.results if r.error is None and r.status_code < 500]

    @property
    def failed(self) -> list[RequestResult]:
        return [r for r in self.results if r.error is not None or r.status_code >= 500]

    @property
    def latencies_ms(self) -> list[float]:
        return [r.latency_ms for r in self.successful]

    # ── Statistics ─────────────────────────────────────────────────────────────

    def percentile(self, pct: float) -> float:
        """Return the pct-th percentile latency in ms."""
        if not self.latencies_ms:
            return 0.0
        s = sorted(self.latencies_ms)
        idx = min(int(len(s) * pct / 100), len(s) - 1)
        return s[idx]

    @property
    def p50(self) -> float:
        return self.percentile(50)

    @property
    def p95(self) -> float:
        return self.percentile(95)

    @property
    def p99(self) -> float:
        return self.percentile(99)

    @property
    def mean_ms(self) -> float:
        return statistics.mean(self.latencies_ms) if self.latencies_ms else 0.0

    @property
    def stdev_ms(self) -> float:
        return statistics.stdev(self.latencies_ms) if len(self.latencies_ms) >= 2 else 0.0

    # ── Throughput + costs ─────────────────────────────────────────────────────

    @property
    def throughput_rps(self) -> float:
        return len(self.results) / self.duration_s if self.duration_s else 0.0

    @property
    def failure_rate(self) -> float:
        return len(self.failed) / len(self.results) if self.results else 0.0

    @property
    def avg_db_queries(self) -> float:
        qs = [r.db_queries for r in self.successful if r.db_queries]
        return statistics.mean(qs) if qs else 0.0

    @property
    def avg_redis_ops(self) -> float:
        ops = [r.redis_ops for r in self.successful if r.redis_ops]
        return statistics.mean(ops) if ops else 0.0

    @property
    def total_redis_ops(self) -> int:
        return sum(r.redis_ops for r in self.successful)

    @property
    def redis_ops_per_sec(self) -> float:
        return self.total_redis_ops / self.duration_s if self.duration_s else 0.0

    # ── Formatting ─────────────────────────────────────────────────────────────

    def summary_line(self) -> str:
        return (
            f"{self.endpoint:40s} | "
            f"n={self.total:5d} c={self.concurrency:4d} | "
            f"p50={self.p50:6.1f}ms p95={self.p95:6.1f}ms p99={self.p99:6.1f}ms | "
            f"rps={self.throughput_rps:7.1f} | "
            f"err={self.failure_rate:.1%}"
        )


# ── Core runner ───────────────────────────────────────────────────────────────

async def run_load(
    fn: Callable[[int], Awaitable[RequestResult]],
    *,
    endpoint: str,
    total: int = 100,
    concurrency: int = 10,
) -> RunReport:
    """
    Execute `total` requests with at most `concurrency` inflight simultaneously.

    Args:
        fn:          Async callable that receives a request index (0…total-1)
                     and returns a RequestResult.  The latency_ms field is set
                     by the runner — fn should leave it at 0.
        endpoint:    Human-readable label for the operation.
        total:       Total number of requests to fire.
        concurrency: Semaphore depth (max simultaneous coroutines).

    Returns:
        RunReport with per-request results and aggregated statistics.
    """
    sem = asyncio.Semaphore(concurrency)

    async def _guarded(idx: int) -> RequestResult:
        async with sem:
            t0 = time.perf_counter()
            try:
                result = await fn(idx)
                result.latency_ms = (time.perf_counter() - t0) * 1000
                return result
            except Exception as exc:
                return RequestResult(
                    latency_ms=(time.perf_counter() - t0) * 1000,
                    status_code=0,
                    error=str(exc),
                )

    t_start = time.perf_counter()
    raw = await asyncio.gather(*[_guarded(i) for i in range(total)])
    duration = time.perf_counter() - t_start

    return RunReport(
        endpoint=endpoint,
        total=total,
        concurrency=concurrency,
        duration_s=duration,
        results=list(raw),
    )


async def run_mixed_load(
    scenarios: list[tuple[Callable[[int], Awaitable[RequestResult]], str]],
    *,
    total_per_scenario: int = 100,
    concurrency: int = 20,
) -> list[RunReport]:
    """
    Run multiple scenarios concurrently, interleaved by the global semaphore.

    Returns one RunReport per scenario.
    """
    results_by_scenario: list[list[RequestResult]] = [[] for _ in scenarios]
    sem = asyncio.Semaphore(concurrency)
    n = len(scenarios)

    async def _one(scenario_idx: int, req_idx: int) -> None:
        fn, _ = scenarios[scenario_idx]
        async with sem:
            t0 = time.perf_counter()
            try:
                result = await fn(req_idx)
                result.latency_ms = (time.perf_counter() - t0) * 1000
            except Exception as exc:
                result = RequestResult(
                    latency_ms=(time.perf_counter() - t0) * 1000,
                    status_code=0,
                    error=str(exc),
                )
            results_by_scenario[scenario_idx].append(result)

    t_start = time.perf_counter()
    tasks = [
        _one(s_idx, r_idx)
        for r_idx in range(total_per_scenario)
        for s_idx in range(n)
    ]
    await asyncio.gather(*tasks)
    duration = time.perf_counter() - t_start

    reports = []
    for idx, (_, label) in enumerate(scenarios):
        reports.append(
            RunReport(
                endpoint=label,
                total=total_per_scenario,
                concurrency=concurrency,
                duration_s=duration,
                results=results_by_scenario[idx],
            )
        )
    return reports

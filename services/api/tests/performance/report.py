"""
Performance Report
==================
Generates a structured console report from a list of RunReports.
All output goes to stdout so pytest -s shows it; pytest without -s
captures it and shows it only on failure.
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from typing import Optional

from tests.performance.load_runner import RunReport
from tests.performance.instrumentation import DB_QUERY_USD, REDIS_OP_USD, COMPUTE_PER_MS_USD


# ── ANSI helpers ──────────────────────────────────────────────────────────────

def _c(text: str, code: str) -> str:
    """Wrap text in ANSI colour code (only when writing to a real TTY)."""
    if not sys.stdout.isatty():
        return text
    return f"\033[{code}m{text}\033[0m"


def _green(t):  return _c(t, "32")
def _yellow(t): return _c(t, "33")
def _red(t):    return _c(t, "31")
def _bold(t):   return _c(t, "1")
def _cyan(t):   return _c(t, "36")


# ── Latency budget thresholds ─────────────────────────────────────────────────

BUDGETS_MS: dict[str, float] = {
    "read":   100.0,   # GET /health, GET /me (token only, no bcrypt)
    "auth":   150.0,   # lightweight auth checks (token decode + DB read)
    "write":  300.0,   # DB writes, non-bcrypt
    "bcrypt": 800.0,   # login / register — dominated by intentional bcrypt slowness
    "redis": 5000.0,   # Redis-only ops batch (measured as total, not per-req)
}


def _latency_colour(latency_ms: float, budget_ms: float) -> str:
    if latency_ms <= budget_ms * 0.6:
        return _green(f"{latency_ms:6.1f}ms")
    if latency_ms <= budget_ms:
        return _yellow(f"{latency_ms:6.1f}ms")
    return _red(f"{latency_ms:6.1f}ms")


def _failure_colour(rate: float) -> str:
    txt = f"{rate:.1%}"
    if rate < 0.001:
        return _green(txt)
    if rate < 0.01:
        return _yellow(txt)
    return _red(txt)


# ── Cost projection ───────────────────────────────────────────────────────────

def _cost_per_10k(report: RunReport) -> float:
    """Estimated USD cost for 10 000 requests at observed metrics."""
    db_cost    = report.avg_db_queries * DB_QUERY_USD
    redis_cost = report.avg_redis_ops  * REDIS_OP_USD
    compute    = report.mean_ms        * COMPUTE_PER_MS_USD
    return (db_cost + redis_cost + compute) * 10_000


# ── Public API ────────────────────────────────────────────────────────────────

def print_report(
    reports: list[RunReport],
    *,
    title: str = "SONORO PERFORMANCE REPORT",
    budget_category: Optional[str] = None,
) -> None:
    """
    Print a formatted performance report to stdout.

    Args:
        reports:         List of RunReports to include.
        title:           Banner heading.
        budget_category: Key into BUDGETS_MS used to colour p95 values.
                         If None, no colouring is applied.
    """
    budget = BUDGETS_MS.get(budget_category or "", float("inf"))
    width = 110
    now = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    def _hr(char="─"): print(char * width)
    def _row(*cols, widths=None):
        if widths is None:
            print("  ".join(str(c) for c in cols))
        else:
            parts = [str(c).ljust(w) for c, w in zip(cols, widths)]
            print("  ".join(parts))

    print()
    _hr("═")
    print(_bold(f"  {title}".center(width)))
    print(f"  Generated: {now}".center(width))
    _hr("═")

    # ── Latency table ──────────────────────────────────────────────────────────
    print()
    print(_bold(_cyan("  LATENCY (in-process ASGI, no network overhead)")))
    _hr()
    print(
        f"  {'Endpoint':<42} {'N':>5} {'C':>4}  "
        f"{'p50':>8} {'p95':>8} {'p99':>8}  "
        f"{'mean':>8} {'stdev':>7}  {'RPS':>8}  {'Err':>6}"
    )
    _hr()

    for r in reports:
        p95_str = _latency_colour(r.p95, budget) if budget_category else f"{r.p95:6.1f}ms"
        print(
            f"  {r.endpoint:<42} {r.total:>5} {r.concurrency:>4}  "
            f"{r.p50:>7.1f}ms {p95_str}  "
            f"{r.p99:>7.1f}ms  {r.mean_ms:>7.1f}ms "
            f"{r.stdev_ms:>6.1f}ms  "
            f"{r.throughput_rps:>8.1f}  "
            f"{_failure_colour(r.failure_rate):>6}"
        )

    _hr()

    # ── Redis / DB ops ─────────────────────────────────────────────────────────
    has_redis = any(r.total_redis_ops > 0 for r in reports)
    has_db    = any(r.avg_db_queries  > 0 for r in reports)

    if has_redis or has_db:
        print()
        print(_bold(_cyan("  OP COUNTS PER REQUEST")))
        _hr()
        print(f"  {'Endpoint':<42}  {'DB queries/req':>16}  {'Redis ops/req':>14}  {'Redis ops/sec':>14}")
        _hr()
        for r in reports:
            if r.avg_db_queries or r.avg_redis_ops:
                print(
                    f"  {r.endpoint:<42}  {r.avg_db_queries:>16.1f}  "
                    f"{r.avg_redis_ops:>14.1f}  {r.redis_ops_per_sec:>14.1f}"
                )
        _hr()

    # ── Cost model ─────────────────────────────────────────────────────────────
    print()
    print(_bold(_cyan("  COST PROJECTION  (DB $10/M queries · Redis $0.50/M ops · Compute $0.03/M req-sec)")))
    _hr()
    print(f"  {'Endpoint':<42}  {'$/10k reqs':>12}  {'$/1M reqs':>12}  {'$/1M reqs/month':>16}")
    _hr()
    total_daily_cost = 0.0
    for r in reports:
        per10k = _cost_per_10k(r)
        per1m  = per10k * 100
        total_daily_cost += per1m
        print(f"  {r.endpoint:<42}  ${per10k:>11.4f}  ${per1m:>11.4f}  ${per1m * 30:>14.2f}")
    _hr()
    print(f"  {'TOTAL (all endpoints, 1M req each, 30 days)':<42}  {'':>12}  {'':>12}  ${total_daily_cost * 30:>14.2f}")
    _hr()

    # ── Budget check ───────────────────────────────────────────────────────────
    if budget_category and budget_category in BUDGETS_MS:
        print()
        print(_bold(_cyan(f"  LATENCY BUDGET: {budget_category.upper()} endpoints → p95 < {budget:.0f}ms")))
        _hr()
        passed = [r for r in reports if r.p95 <= budget]
        failed = [r for r in reports if r.p95 > budget]
        for r in passed:
            print(f"  {_green('PASS')}  {r.endpoint}  p95={r.p95:.1f}ms ≤ {budget:.0f}ms")
        for r in failed:
            print(f"  {_red('FAIL')}  {r.endpoint}  p95={r.p95:.1f}ms > {budget:.0f}ms")
        _hr()

    print()


def print_redis_pressure_report(
    *,
    total_ops: int,
    duration_s: float,
    breakdown: dict[str, int],
    user_count: int,
    collision_count: int = 0,
) -> None:
    """Print a Redis-specific pressure report."""
    width = 80
    ops_per_sec = total_ops / duration_s if duration_s else 0

    print()
    print("=" * width)
    print(_bold("  REDIS PRESSURE REPORT".center(width)))
    print("=" * width)
    print(f"  Total ops     : {total_ops:>12,}")
    print(f"  Duration      : {duration_s:>12.2f}s")
    print(f"  Ops/sec       : {ops_per_sec:>12,.0f}")
    print(f"  Unique users  : {user_count:>12,}")
    print(f"  Key collisions: {collision_count:>12,}  {'✓ NONE' if collision_count == 0 else '✗ DETECTED'}")
    print()
    print("  Breakdown:")
    for op, count in sorted(breakdown.items(), key=lambda x: -x[1]):
        pct = count / total_ops * 100 if total_ops else 0
        print(f"    {op:<20} {count:>10,}  ({pct:5.1f}%)")
    print("=" * width)
    print()

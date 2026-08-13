"""
Unit Tests: Rate Limit Dependency (Phase 0D / audit 0.9)
========================================================
Regression coverage for F-29: RateLimitService existed, was tested, and had an
UPLOAD tier configured — but nothing called it, so the endpoints that spend
money had no rate limit at all.

The invariants these tests protect:
  - The money endpoints carry the limit, declared on the route.
  - Exceeding it returns 429 with Retry-After, not a 500.
  - Redis being down allows the request through (fail open) — spend is already
    bounded by the Phase 0C cost guard, which does not depend on Redis.
  - The limit runs BEFORE the request reaches the handler, so a rejected
    request never creates a job or spends money.
"""
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.financial.rate_limit.dependencies import rate_limit
from app.financial.rate_limit.rate_limit_service import RateLimitTier
from tests.fakes import FakeRedis

pytestmark = pytest.mark.unit


def _request(path: str = "/api/v1/documents/upload"):
    return SimpleNamespace(url=SimpleNamespace(path=path))


def _user():
    return SimpleNamespace(id=uuid4())


async def _call(dep, redis, *, enabled=True, user=None):
    """Invoke the dependency with a given Redis and flag state."""
    user = user or _user()
    with patch("app.financial.rate_limit.dependencies.settings.feature_rate_limiting", enabled):
        with patch(
            "app.financial.rate_limit.dependencies.get_redis",
            new_callable=AsyncMock, return_value=redis,
        ):
            return await dep(_request(), user)


# ── Under the limit → allowed ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_request_under_limit_is_allowed():
    dep = rate_limit(RateLimitTier.UPLOAD)
    assert await _call(dep, FakeRedis()) is None


@pytest.mark.asyncio
async def test_upload_tier_allows_a_normal_burst():
    """10/min is the UPLOAD tier — a user uploading a few books must not trip it."""
    dep = rate_limit(RateLimitTier.UPLOAD)
    redis, user = FakeRedis(), _user()
    for _ in range(10):
        assert await _call(dep, redis, user=user) is None


# ── Over the limit → 429, not 500 ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_exceeding_limit_raises_429_with_retry_after():
    dep = rate_limit(RateLimitTier.UPLOAD)
    redis, user = FakeRedis(), _user()

    for _ in range(10):          # exhaust the per-minute allowance
        await _call(dep, redis, user=user)

    with pytest.raises(HTTPException) as exc:
        await _call(dep, redis, user=user)

    assert exc.value.status_code == 429
    assert "Retry-After" in exc.value.headers
    # The message must be actionable and must not leak internals.
    assert "try again" in exc.value.detail.lower()


@pytest.mark.asyncio
async def test_limits_are_per_user():
    """One user exhausting their allowance must not block anybody else."""
    dep = rate_limit(RateLimitTier.UPLOAD)
    redis, heavy = FakeRedis(), _user()

    for _ in range(10):
        await _call(dep, redis, user=heavy)
    with pytest.raises(HTTPException):
        await _call(dep, redis, user=heavy)

    assert await _call(dep, redis, user=_user()) is None


# ── Failure and flag behaviour ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_redis_failure_fails_open():
    """
    Rate limiting bounds abuse rate; the Phase 0C cost guard bounds money and
    does not need Redis.  A Redis outage must not stop paying customers.
    """
    dep = rate_limit(RateLimitTier.UPLOAD)
    with patch(
        "app.financial.rate_limit.dependencies.get_redis",
        new_callable=AsyncMock, side_effect=RuntimeError("redis down"),
    ):
        with patch(
            "app.financial.rate_limit.dependencies.settings.feature_rate_limiting", True
        ):
            assert await dep(_request(), _user()) is None


@pytest.mark.asyncio
async def test_disabled_flag_skips_redis_entirely():
    dep = rate_limit(RateLimitTier.UPLOAD)
    with patch(
        "app.financial.rate_limit.dependencies.get_redis", new_callable=AsyncMock
    ) as mock_redis:
        with patch(
            "app.financial.rate_limit.dependencies.settings.feature_rate_limiting", False
        ):
            assert await dep(_request(), _user()) is None
    mock_redis.assert_not_awaited()


def test_rate_limiting_is_enabled_by_default():
    """A limit that ships disabled is not a limit (F-29)."""
    from app.core.config import Settings

    assert Settings.model_fields["feature_rate_limiting"].default is True


# ── The money endpoints actually carry the limit ──────────────────────────────
# Declared on the route, so a handler edit cannot silently drop it.

MONEY_ROUTES = {
    ("/api/v1/documents/upload", "POST"),
    ("/api/v1/documents/{document_id}/process", "POST"),
    ("/api/v1/documents/{document_id}/retry", "POST"),
}


def _rate_limited_routes():
    from app.routers.documents import router

    found = set()
    for route in router.routes:
        deps = getattr(route, "dependencies", [])
        if any("_enforce" in getattr(d.dependency, "__name__", "") for d in deps):
            for method in route.methods:
                found.add((route.path, method))
    return found


def test_every_job_creating_endpoint_is_rate_limited():
    """upload / process / retry all enqueue paid work — all three must be covered."""
    assert MONEY_ROUTES.issubset(_rate_limited_routes())


def test_free_endpoints_are_not_rate_limited():
    """Cancel costs nothing and must stay available even under an abuse burst."""
    limited = _rate_limited_routes()
    assert ("/api/v1/documents/{document_id}/cancel", "POST") not in limited

"""
Unit Tests: RateLimitService
=============================
Pure-logic tests using FakeRedis.  No DB, no HTTP, no real Redis.

time.time() is patched to return monotonically increasing integers so
that sorted-set member keys (which are str(now)) never collide even
when the test loop runs faster than clock resolution.
"""
import itertools
import pytest

import app.financial.rate_limit.rate_limit_service as _rl_mod
from tests.fakes import FakeRedis
from app.financial.rate_limit.rate_limit_service import (
    RateLimitService,
    RateLimitTier,
    RateLimitConfig,
    RateLimitExceeded,
)

pytestmark = pytest.mark.unit

# AUTH tier defaults: 5/min  20/hr  100/day
# API  tier defaults: 60/min 1000/hr 10000/day


@pytest.fixture
def redis() -> FakeRedis:
    return FakeRedis()


@pytest.fixture
def svc(redis: FakeRedis) -> RateLimitService:
    return RateLimitService(redis=redis)


@pytest.fixture(autouse=True)
def _monotonic_time(monkeypatch):
    """Replace time.time() in rate_limit_service with a counter so member
    keys in the sorted set are always unique."""
    counter = itertools.count(start=1_000_000)

    class _T:
        @staticmethod
        def time() -> float:
            return float(next(counter))

    monkeypatch.setattr(_rl_mod, "time", _T())


# ── Allow / deny basics ───────────────────────────────────────────────────────

async def test_first_request_is_always_allowed(svc):
    allowed, retry_after = await svc.check_rate_limit("u1", RateLimitTier.API)
    assert allowed is True
    assert retry_after is None


async def test_requests_within_auth_minute_limit_are_allowed(svc):
    for _ in range(5):
        allowed, _ = await svc.check_rate_limit("u1", RateLimitTier.AUTH)
        assert allowed is True


async def test_exceeding_auth_minute_limit_raises(svc):
    for _ in range(5):
        await svc.check_rate_limit("u1", RateLimitTier.AUTH)

    with pytest.raises(RateLimitExceeded):
        await svc.check_rate_limit("u1", RateLimitTier.AUTH)


async def test_exceeded_exception_carries_retry_after(svc):
    for _ in range(5):
        await svc.check_rate_limit("u1", RateLimitTier.AUTH)

    with pytest.raises(RateLimitExceeded) as exc:
        await svc.check_rate_limit("u1", RateLimitTier.AUTH)

    assert exc.value.retry_after is not None
    assert exc.value.retry_after > 0


async def test_exceeded_exception_carries_limit_and_window(svc):
    for _ in range(5):
        await svc.check_rate_limit("u1", RateLimitTier.AUTH)

    with pytest.raises(RateLimitExceeded) as exc:
        await svc.check_rate_limit("u1", RateLimitTier.AUTH)

    assert exc.value.limit == 5    # AUTH minute limit
    assert exc.value.window == 60  # seconds


# ── Tier differentiation ──────────────────────────────────────────────────────

async def test_api_tier_minute_limit_is_higher_than_auth(svc):
    # 10 requests should NOT exhaust the API tier (60/min)
    for _ in range(10):
        await svc.check_rate_limit("u2", RateLimitTier.API)
    allowed, _ = await svc.check_rate_limit("u2", RateLimitTier.API)
    assert allowed is True


async def test_admin_tier_more_permissive_than_auth_tier(svc):
    admin_rpm = svc._rate_limits[RateLimitTier.ADMIN].requests_per_minute
    auth_rpm = svc._rate_limits[RateLimitTier.AUTH].requests_per_minute
    assert admin_rpm > auth_rpm


# ── User isolation ────────────────────────────────────────────────────────────

async def test_different_users_tracked_independently(svc):
    # Exhaust user-A's AUTH limit
    for _ in range(5):
        await svc.check_rate_limit("user-A", RateLimitTier.AUTH)

    with pytest.raises(RateLimitExceeded):
        await svc.check_rate_limit("user-A", RateLimitTier.AUTH)

    # user-B is unaffected
    allowed, _ = await svc.check_rate_limit("user-B", RateLimitTier.AUTH)
    assert allowed is True


# ── Reset ─────────────────────────────────────────────────────────────────────

async def test_reset_clears_exhausted_limit(svc):
    for _ in range(5):
        await svc.check_rate_limit("u-reset", RateLimitTier.AUTH)

    with pytest.raises(RateLimitExceeded):
        await svc.check_rate_limit("u-reset", RateLimitTier.AUTH)

    await svc.reset("u-reset", RateLimitTier.AUTH)

    allowed, _ = await svc.check_rate_limit("u-reset", RateLimitTier.AUTH)
    assert allowed is True


# ── get_limits ────────────────────────────────────────────────────────────────

async def test_get_limits_shows_used_count(svc):
    for _ in range(3):
        await svc.check_rate_limit("u-limits", RateLimitTier.AUTH)

    info = await svc.get_limits("u-limits", RateLimitTier.AUTH)

    assert info["minute"]["used"] == 3
    assert info["minute"]["limit"] == 5
    assert info["minute"]["remaining"] == 2


async def test_get_limits_fresh_user_is_fully_remaining(svc):
    info = await svc.get_limits("fresh", RateLimitTier.API)
    assert info["minute"]["used"] == 0
    assert info["minute"]["remaining"] == info["minute"]["limit"]


async def test_get_limits_has_all_three_windows(svc):
    info = await svc.get_limits("u-wins", RateLimitTier.API)
    assert "minute" in info
    assert "hour" in info
    assert "day" in info


# ── Custom configuration ──────────────────────────────────────────────────────

async def test_configure_limit_overrides_default(svc):
    custom = RateLimitConfig(
        requests_per_minute=2,
        requests_per_hour=10,
        requests_per_day=50,
        burst_size=5,
    )
    svc.configure_limit(RateLimitTier.AUTH, custom)

    for _ in range(2):
        await svc.check_rate_limit("u-custom", RateLimitTier.AUTH)

    with pytest.raises(RateLimitExceeded):
        await svc.check_rate_limit("u-custom", RateLimitTier.AUTH)


# ── Key namespacing ───────────────────────────────────────────────────────────

def test_key_contains_user_tier_and_window(svc):
    key = svc._make_key("user123", RateLimitTier.AUTH, "minute")
    assert "user123" in key
    assert "auth" in key
    assert "minute" in key


def test_key_contains_endpoint_when_given(svc):
    key = svc._make_key("user123", RateLimitTier.API, "minute", "/upload")
    assert "/upload" in key


def test_different_tiers_produce_different_keys(svc):
    k_auth = svc._make_key("u1", RateLimitTier.AUTH, "minute")
    k_api = svc._make_key("u1", RateLimitTier.API, "minute")
    assert k_auth != k_api


def test_different_windows_produce_different_keys(svc):
    k_min = svc._make_key("u1", RateLimitTier.API, "minute")
    k_hour = svc._make_key("u1", RateLimitTier.API, "hour")
    assert k_min != k_hour

"""
Billing Enforcement Service Tests
====================================
Validates quota enforcement, suspension detection, and grace-period handling.
"""
from __future__ import annotations

import uuid

import pytest

from app.billing.enforcement import BillingEnforcementService, AccountSuspended, QuotaExceeded
from app.billing.usage_meter import UsageMeteringService
from app.billing.constants import TIER_DAILY_API_LIMITS




async def test_free_user_under_quota_passes(fake_redis, user_id):
    svc = BillingEnforcementService(fake_redis)
    # No usage recorded → 0 < 100 limit → should pass
    await svc.check(user_id, "free", "FREE")  # must not raise


async def test_free_user_at_quota_raises_quota_exceeded(fake_redis, user_id):
    meter = UsageMeteringService(fake_redis)
    limit = TIER_DAILY_API_LIMITS["FREE"]
    for _ in range(limit):
        await meter.record(user_id, api_calls=1)

    svc = BillingEnforcementService(fake_redis)
    with pytest.raises(QuotaExceeded) as exc_info:
        await svc.check(user_id, "free", "FREE")

    assert exc_info.value.limit == limit
    assert exc_info.value.current >= limit


async def test_suspended_user_raises_account_suspended(fake_redis, user_id):
    svc = BillingEnforcementService(fake_redis)
    with pytest.raises(AccountSuspended) as exc_info:
        await svc.check(user_id, "suspended", "FREE")

    assert exc_info.value.status == "suspended"


async def test_canceled_user_raises_account_suspended(fake_redis, user_id):
    svc = BillingEnforcementService(fake_redis)
    with pytest.raises(AccountSuspended):
        await svc.check(user_id, "canceled", "PRO")


async def test_past_due_user_is_still_allowed(fake_redis, user_id):
    """past_due users are in a grace period — they can still make requests."""
    svc = BillingEnforcementService(fake_redis)
    await svc.check(user_id, "past_due", "BASIC")  # must not raise


async def test_enterprise_user_has_unlimited_quota(fake_redis, user_id):
    """ENTERPRISE tier has limit=-1 (unlimited) — quota check is bypassed."""
    meter = UsageMeteringService(fake_redis)
    # Record 10× the PRO daily limit
    for _ in range(10_000):
        await meter.record(user_id, api_calls=1)

    svc = BillingEnforcementService(fake_redis)
    await svc.check(user_id, "active", "ENTERPRISE")  # must not raise


async def test_basic_user_under_quota_passes(fake_redis, user_id):
    meter = UsageMeteringService(fake_redis)
    for _ in range(500):
        await meter.record(user_id, api_calls=1)

    svc = BillingEnforcementService(fake_redis)
    await svc.check(user_id, "active", "BASIC")  # 500 < 1000 → passes


async def test_basic_user_over_quota_raises(fake_redis, user_id):
    meter = UsageMeteringService(fake_redis)
    limit = TIER_DAILY_API_LIMITS["BASIC"]
    for _ in range(limit):
        await meter.record(user_id, api_calls=1)

    svc = BillingEnforcementService(fake_redis)
    with pytest.raises(QuotaExceeded):
        await svc.check(user_id, "active", "BASIC")


async def test_different_users_have_independent_quotas(fake_redis):
    uid_a = uuid.uuid4()
    uid_b = uuid.uuid4()

    meter = UsageMeteringService(fake_redis)
    limit = TIER_DAILY_API_LIMITS["FREE"]
    for _ in range(limit):
        await meter.record(uid_a, api_calls=1)

    svc = BillingEnforcementService(fake_redis)
    with pytest.raises(QuotaExceeded):
        await svc.check(uid_a, "free", "FREE")

    # uid_b is unaffected
    await svc.check(uid_b, "free", "FREE")  # must not raise


async def test_trial_user_can_make_requests(fake_redis, user_id):
    svc = BillingEnforcementService(fake_redis)
    await svc.check(user_id, "trial", "FREE")  # must not raise

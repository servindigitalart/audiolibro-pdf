"""
Integration Tests: Billing Simulation
=======================================
Simulates billing lifecycle scenarios against the real test DB.
No real Stripe calls — all quota state is managed through the ORM directly.

Tests:
  - quota rows start at zero
  - usage increments are tracked exactly (no overcharging)
  - plan tier upgrades / downgrades affect limit headroom correctly
  - storage tracking persists within a session
  - multiple users have isolated quota rows
  - quota period dates are correctly set to 30-day windows
"""
import pytest
from datetime import datetime, timedelta
from sqlalchemy.ext.asyncio import AsyncSession

from tests.factories import create_user
from app.financial.quota.quota_limits import PlanTier, get_plan_limits
from app.financial.cost.cost_models import UsageQuota

pytestmark = pytest.mark.integration


# ── Helper ────────────────────────────────────────────────────────────────────

async def _make_quota(db: AsyncSession, user) -> UsageQuota:
    """Create a UsageQuota row directly (bypasses QuotaService)."""
    now = datetime.utcnow()
    quota = UsageQuota(
        user_id=user.id,
        period_start=now,
        period_end=now + timedelta(days=30),
        characters_used=0,
        jobs_created=0,
        storage_used_mb=0.0,
        api_calls=0,
    )
    db.add(quota)
    await db.flush()
    await db.refresh(quota)
    return quota


# ── User + tier creation ──────────────────────────────────────────────────────

async def test_free_user_persists_with_correct_tier(db_session: AsyncSession):
    user = await create_user(db_session, plan_tier="FREE")
    assert user.plan_tier == "FREE"


async def test_basic_user_persists_with_correct_tier(db_session: AsyncSession):
    user = await create_user(db_session, plan_tier="BASIC")
    assert user.plan_tier == "BASIC"


async def test_all_plan_tiers_can_be_persisted(db_session: AsyncSession):
    for tier in ("FREE", "BASIC", "PRO", "ENTERPRISE"):
        user = await create_user(db_session, plan_tier=tier)
        await db_session.refresh(user)
        assert user.plan_tier == tier


# ── Quota row lifecycle ───────────────────────────────────────────────────────

async def test_new_quota_starts_at_zero(db_session: AsyncSession):
    user = await create_user(db_session)
    quota = await _make_quota(db_session, user)

    assert quota.characters_used == 0
    assert quota.jobs_created == 0
    assert quota.storage_used_mb == 0.0
    assert quota.api_calls == 0


async def test_quota_period_is_30_days(db_session: AsyncSession):
    user = await create_user(db_session)
    quota = await _make_quota(db_session, user)

    delta = quota.period_end - quota.period_start
    assert abs(delta.total_seconds() - 30 * 24 * 3600) < 2  # 2-second tolerance


# ── Usage tracking exactness (anti-overcharging) ──────────────────────────────

async def test_character_increments_are_exact(db_session: AsyncSession):
    user = await create_user(db_session, plan_tier="PRO")
    quota = await _make_quota(db_session, user)

    quota.characters_used += 1_000
    quota.characters_used += 2_000
    await db_session.flush()
    await db_session.refresh(quota)

    assert quota.characters_used == 3_000


async def test_job_increments_are_exact(db_session: AsyncSession):
    user = await create_user(db_session)
    quota = await _make_quota(db_session, user)

    for _ in range(3):
        quota.jobs_created += 1
    await db_session.flush()
    await db_session.refresh(quota)

    assert quota.jobs_created == 3


async def test_api_call_increments_are_exact(db_session: AsyncSession):
    user = await create_user(db_session)
    quota = await _make_quota(db_session, user)

    quota.api_calls += 50
    await db_session.flush()
    await db_session.refresh(quota)

    assert quota.api_calls == 50


# ── Quota exhaustion simulation ───────────────────────────────────────────────

async def test_free_tier_character_limit_exhaustion(db_session: AsyncSession):
    user = await create_user(db_session, plan_tier="FREE")
    quota = await _make_quota(db_session, user)
    limits = get_plan_limits(PlanTier.FREE)

    quota.characters_used = limits.monthly_char_limit
    await db_session.flush()
    await db_session.refresh(quota)

    remaining = max(0, limits.monthly_char_limit - quota.characters_used)
    assert remaining == 0


async def test_free_tier_job_limit_exhaustion(db_session: AsyncSession):
    user = await create_user(db_session, plan_tier="FREE")
    quota = await _make_quota(db_session, user)
    limits = get_plan_limits(PlanTier.FREE)

    quota.jobs_created = limits.monthly_job_limit
    await db_session.flush()
    await db_session.refresh(quota)

    assert quota.jobs_created == limits.monthly_job_limit


async def test_storage_limit_exhaustion(db_session: AsyncSession):
    user = await create_user(db_session, plan_tier="FREE")
    quota = await _make_quota(db_session, user)
    limits = get_plan_limits(PlanTier.FREE)

    quota.storage_used_mb = limits.storage_limit_mb
    await db_session.flush()
    await db_session.refresh(quota)

    remaining = max(0.0, limits.storage_limit_mb - quota.storage_used_mb)
    assert remaining == 0.0


# ── Tier upgrade / downgrade ──────────────────────────────────────────────────

async def test_upgrade_free_to_basic_gives_more_headroom(db_session: AsyncSession):
    user = await create_user(db_session, plan_tier="FREE")

    free_chars = get_plan_limits(PlanTier.FREE).monthly_char_limit
    basic_chars = get_plan_limits(PlanTier.BASIC).monthly_char_limit

    user.plan_tier = "BASIC"
    await db_session.flush()
    await db_session.refresh(user)

    assert user.plan_tier == "BASIC"
    assert basic_chars > free_chars


async def test_upgrade_basic_to_pro_multiplies_headroom(db_session: AsyncSession):
    user = await create_user(db_session, plan_tier="BASIC")

    basic_chars = get_plan_limits(PlanTier.BASIC).monthly_char_limit
    pro_chars = get_plan_limits(PlanTier.PRO).monthly_char_limit

    user.plan_tier = "PRO"
    await db_session.flush()

    assert pro_chars > basic_chars


async def test_downgrade_pro_to_basic_reduces_job_limit(db_session: AsyncSession):
    user = await create_user(db_session, plan_tier="PRO")

    pro_jobs = get_plan_limits(PlanTier.PRO).monthly_job_limit
    basic_jobs = get_plan_limits(PlanTier.BASIC).monthly_job_limit

    user.plan_tier = "BASIC"
    await db_session.flush()

    assert basic_jobs < pro_jobs


# ── User isolation (no cross-billing) ────────────────────────────────────────

async def test_two_users_have_independent_quotas(db_session: AsyncSession):
    user_a = await create_user(db_session, plan_tier="FREE")
    user_b = await create_user(db_session, plan_tier="FREE")

    quota_a = await _make_quota(db_session, user_a)
    quota_b = await _make_quota(db_session, user_b)

    limits = get_plan_limits(PlanTier.FREE)
    quota_a.characters_used = limits.monthly_char_limit
    await db_session.flush()
    await db_session.refresh(quota_a)
    await db_session.refresh(quota_b)

    assert quota_b.characters_used == 0  # user_b not affected


async def test_quota_user_id_matches_owner(db_session: AsyncSession):
    user = await create_user(db_session)
    quota = await _make_quota(db_session, user)
    assert quota.user_id == user.id

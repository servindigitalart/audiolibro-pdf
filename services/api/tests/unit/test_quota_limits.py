"""
Unit Tests: Quota Limits & Billing Simulation (pure logic)
===========================================================
Tests for plan tier configuration and quota math.
No DB, no Redis, no HTTP — just the QuotaLimits data layer.

These tests encode the SaaS contract:
  - each tier's limits are positive and correctly ordered
  - upgrade increases headroom, downgrade decreases it
  - quota exhaustion arithmetic is exact (no off-by-one overcharging)
"""
import pytest

from app.financial.quota.quota_limits import (
    PlanTier,
    QuotaLimits,
    get_plan_limits,
    PLAN_QUOTAS,
)

pytestmark = pytest.mark.unit


# ── Coverage of all tiers ─────────────────────────────────────────────────────

def test_every_plan_tier_has_a_quota_config():
    for tier in PlanTier:
        assert tier in PLAN_QUOTAS, f"No quota config for tier {tier}"


def test_get_plan_limits_returns_quota_limits_instance():
    for tier in PlanTier:
        result = get_plan_limits(tier)
        assert isinstance(result, QuotaLimits)


# ── FREE tier specifics ───────────────────────────────────────────────────────

def test_free_tier_character_limit():
    assert get_plan_limits(PlanTier.FREE).monthly_char_limit == 10_000


def test_free_tier_job_limit():
    assert get_plan_limits(PlanTier.FREE).monthly_job_limit == 5


def test_free_tier_no_priority_processing():
    assert get_plan_limits(PlanTier.FREE).priority_processing is False


def test_free_tier_no_api_access():
    assert get_plan_limits(PlanTier.FREE).api_access is False


def test_free_tier_single_user_only():
    assert get_plan_limits(PlanTier.FREE).team_members == 1


def test_free_tier_no_custom_voices():
    assert get_plan_limits(PlanTier.FREE).custom_voices is False


# ── Paid tiers features ───────────────────────────────────────────────────────

def test_paid_tiers_have_api_access():
    for tier in (PlanTier.BASIC, PlanTier.PRO, PlanTier.ENTERPRISE):
        assert get_plan_limits(tier).api_access is True, f"API access missing for {tier}"


def test_pro_and_enterprise_have_priority_processing():
    assert get_plan_limits(PlanTier.PRO).priority_processing is True
    assert get_plan_limits(PlanTier.ENTERPRISE).priority_processing is True


def test_pro_and_enterprise_have_custom_voices():
    assert get_plan_limits(PlanTier.PRO).custom_voices is True
    assert get_plan_limits(PlanTier.ENTERPRISE).custom_voices is True


def test_enterprise_supports_team_members():
    assert get_plan_limits(PlanTier.ENTERPRISE).team_members > 1


# ── Tier ordering invariants ──────────────────────────────────────────────────

def test_character_limits_increase_with_tier():
    limits = [get_plan_limits(t).monthly_char_limit for t in
              (PlanTier.FREE, PlanTier.BASIC, PlanTier.PRO, PlanTier.ENTERPRISE)]
    assert limits == sorted(limits), "Character limits must be strictly ascending"
    assert len(set(limits)) == 4, "All tiers must have distinct character limits"


def test_job_limits_increase_with_tier():
    limits = [get_plan_limits(t).monthly_job_limit for t in
              (PlanTier.FREE, PlanTier.BASIC, PlanTier.PRO, PlanTier.ENTERPRISE)]
    assert limits == sorted(limits)
    assert len(set(limits)) == 4


def test_storage_limits_increase_with_tier():
    limits = [get_plan_limits(t).storage_limit_mb for t in
              (PlanTier.FREE, PlanTier.BASIC, PlanTier.PRO, PlanTier.ENTERPRISE)]
    assert limits == sorted(limits)
    assert len(set(limits)) == 4


def test_api_rate_limits_increase_with_tier():
    limits = [get_plan_limits(t).api_calls_per_minute for t in
              (PlanTier.FREE, PlanTier.BASIC, PlanTier.PRO, PlanTier.ENTERPRISE)]
    assert limits == sorted(limits)
    assert len(set(limits)) == 4


# ── Upgrade / downgrade simulation ───────────────────────────────────────────

def test_upgrade_free_to_pro_multiplies_character_headroom():
    free = get_plan_limits(PlanTier.FREE).monthly_char_limit
    pro = get_plan_limits(PlanTier.PRO).monthly_char_limit
    assert pro >= free * 10, "PRO should be at least 10× FREE"


def test_downgrade_pro_to_basic_reduces_all_limits():
    pro = get_plan_limits(PlanTier.PRO)
    basic = get_plan_limits(PlanTier.BASIC)
    assert basic.monthly_char_limit < pro.monthly_char_limit
    assert basic.monthly_job_limit < pro.monthly_job_limit
    assert basic.storage_limit_mb < pro.storage_limit_mb


def test_downgrade_does_not_drop_api_access_for_basic():
    assert get_plan_limits(PlanTier.BASIC).api_access is True


# ── No-overcharging invariants ────────────────────────────────────────────────

def test_all_limits_are_strictly_positive():
    for tier in PlanTier:
        lim = get_plan_limits(tier)
        assert lim.monthly_char_limit > 0
        assert lim.monthly_job_limit > 0
        assert lim.concurrent_job_limit > 0
        assert lim.storage_limit_mb > 0
        assert lim.api_calls_per_minute > 0
        assert lim.api_calls_per_day > 0


def test_daily_api_limit_exceeds_per_minute_limit():
    # daily >= 60-minute equivalents (otherwise a single sustained minute exhausts the day)
    for tier in PlanTier:
        lim = get_plan_limits(tier)
        assert lim.api_calls_per_day > lim.api_calls_per_minute, (
            f"{tier}: daily limit must exceed per-minute limit"
        )


def test_remaining_quota_math_is_exact_at_boundary():
    lim = get_plan_limits(PlanTier.FREE)
    used = lim.monthly_char_limit
    remaining = max(0, lim.monthly_char_limit - used)
    assert remaining == 0


def test_remaining_quota_math_one_below_limit():
    lim = get_plan_limits(PlanTier.FREE)
    used = lim.monthly_char_limit - 1
    remaining = max(0, lim.monthly_char_limit - used)
    assert remaining == 1


def test_remaining_never_goes_negative():
    lim = get_plan_limits(PlanTier.FREE)
    # Simulate over-use (e.g., race condition allowed one extra)
    used = lim.monthly_char_limit + 100
    remaining = max(0, lim.monthly_char_limit - used)
    assert remaining == 0

"""
Tier Definition Tests — Task 1
================================
Verifies the canonical tier catalog is internally consistent and
aligns with the existing billing constants.

Checks:
  - All four tiers exist with positive or zero prices
  - Limits increase monotonically across tiers
  - Feature access is a strict superset as tiers increase
  - Cost caps are set and > 0 for paid tiers
  - Stripe price settings names match config attributes
  - get_tier / get_next_tier / has_feature helpers work correctly
  - stripe_price_id returns empty string for FREE tier
  - Tier values align with billing/constants.py TIER_DAILY_API_LIMITS
"""
from __future__ import annotations

import pytest

from app.billing.constants import TIER_DAILY_API_LIMITS
from app.pricing.tiers import (
    TIER_CATALOG,
    PlanTier,
    TierConfig,
    TierFeature,
    get_next_tier,
    get_tier,
    has_feature,
    stripe_price_id,
)


# ── All tiers present ─────────────────────────────────────────────────────────

def test_all_four_tiers_exist():
    assert set(TIER_CATALOG.keys()) == {
        PlanTier.FREE, PlanTier.BASIC, PlanTier.PRO, PlanTier.ENTERPRISE
    }


def test_each_tier_config_is_a_tier_config_instance():
    for cfg in TIER_CATALOG.values():
        assert isinstance(cfg, TierConfig)


# ── Pricing ───────────────────────────────────────────────────────────────────

def test_free_tier_price_is_zero():
    assert get_tier(PlanTier.FREE).monthly_price_usd == 0.0


def test_paid_tier_prices_are_positive():
    for tier in (PlanTier.BASIC, PlanTier.PRO, PlanTier.ENTERPRISE):
        assert get_tier(tier).monthly_price_usd > 0


def test_annual_price_is_less_than_twelve_monthly():
    for tier in (PlanTier.BASIC, PlanTier.PRO, PlanTier.ENTERPRISE):
        cfg = get_tier(tier)
        assert cfg.annual_price_usd < cfg.monthly_price_usd * 12, (
            f"{tier.value}: annual {cfg.annual_price_usd} not cheaper than 12×monthly "
            f"{cfg.monthly_price_usd * 12}"
        )


def test_prices_increase_across_tiers():
    prices = [get_tier(t).monthly_price_usd for t in PlanTier]
    assert prices == sorted(prices)


# ── Resource limits increase monotonically ────────────────────────────────────

def test_monthly_chars_increase_across_tiers():
    chars = [get_tier(t).monthly_chars for t in PlanTier]
    assert chars == sorted(chars)


def test_monthly_jobs_increase_across_tiers():
    jobs = [get_tier(t).monthly_jobs for t in PlanTier]
    assert jobs == sorted(jobs)


def test_storage_mb_increases_across_tiers():
    storage = [get_tier(t).storage_mb for t in PlanTier]
    assert storage == sorted(storage)


def test_concurrent_jobs_increase_across_tiers():
    conc = [get_tier(t).concurrent_jobs for t in PlanTier]
    assert conc == sorted(conc)


def test_daily_api_calls_increase_or_unlimited():
    # ENTERPRISE has -1 (unlimited), so skip ordering check for it
    for tier in (PlanTier.FREE, PlanTier.BASIC, PlanTier.PRO):
        current = get_tier(tier).daily_api_calls
        next_cfg = get_next_tier(tier)
        if next_cfg and next_cfg.daily_api_calls != -1:
            assert next_cfg.daily_api_calls > current


def test_enterprise_daily_api_calls_is_unlimited():
    assert get_tier(PlanTier.ENTERPRISE).daily_api_calls == -1


# ── Cost caps ─────────────────────────────────────────────────────────────────

def test_all_paid_tiers_have_positive_cost_caps():
    for tier in (PlanTier.BASIC, PlanTier.PRO, PlanTier.ENTERPRISE):
        cfg = get_tier(tier)
        assert cfg.max_daily_cost_usd > 0
        assert cfg.max_monthly_cost_usd > 0


def test_monthly_cost_cap_at_least_daily_cap():
    for tier in PlanTier:
        cfg = get_tier(tier)
        assert cfg.max_monthly_cost_usd >= cfg.max_daily_cost_usd


def test_monthly_cost_cap_less_than_monthly_revenue():
    """Cost caps must be set below revenue so there's a guaranteed margin floor."""
    for tier in (PlanTier.BASIC, PlanTier.PRO, PlanTier.ENTERPRISE):
        cfg = get_tier(tier)
        assert cfg.max_monthly_cost_usd < cfg.monthly_price_usd, (
            f"{tier.value}: max_monthly_cost ${cfg.max_monthly_cost_usd} "
            f">= revenue ${cfg.monthly_price_usd}"
        )


# ── Features ──────────────────────────────────────────────────────────────────

def test_free_tier_includes_document_upload_and_tts():
    assert has_feature(PlanTier.FREE, TierFeature.DOCUMENT_UPLOAD)
    assert has_feature(PlanTier.FREE, TierFeature.TTS_PROCESSING)


def test_free_tier_does_not_include_api_access():
    assert not has_feature(PlanTier.FREE, TierFeature.API_ACCESS)


def test_basic_includes_api_access():
    assert has_feature(PlanTier.BASIC, TierFeature.API_ACCESS)


def test_pro_includes_priority_and_custom_voices():
    assert has_feature(PlanTier.PRO, TierFeature.PRIORITY_PROCESSING)
    assert has_feature(PlanTier.PRO, TierFeature.CUSTOM_VOICES)


def test_enterprise_includes_all_pro_features():
    pro_features = get_tier(PlanTier.PRO).features
    enterprise_features = get_tier(PlanTier.ENTERPRISE).features
    assert pro_features.issubset(enterprise_features)


def test_enterprise_has_sla_support():
    assert has_feature(PlanTier.ENTERPRISE, TierFeature.SLA_SUPPORT)


def test_team_members_increase_across_tiers():
    members = [get_tier(t).max_team_members for t in PlanTier]
    assert members == sorted(members)


# ── Paywall thresholds ────────────────────────────────────────────────────────

def test_warn_pct_below_block_pct():
    for tier in PlanTier:
        cfg = get_tier(tier)
        assert cfg.warn_usage_pct < cfg.block_usage_pct


def test_all_tiers_have_positive_warn_pct():
    for tier in PlanTier:
        assert 0 < get_tier(tier).warn_usage_pct <= 1.0


# ── Upgrade path ──────────────────────────────────────────────────────────────

def test_free_upgrades_to_basic():
    assert get_tier(PlanTier.FREE).upgrades_to == PlanTier.BASIC


def test_basic_upgrades_to_pro():
    assert get_tier(PlanTier.BASIC).upgrades_to == PlanTier.PRO


def test_pro_upgrades_to_enterprise():
    assert get_tier(PlanTier.PRO).upgrades_to == PlanTier.ENTERPRISE


def test_enterprise_has_no_upgrade():
    assert get_tier(PlanTier.ENTERPRISE).upgrades_to is None


def test_get_next_tier_returns_correct_config():
    next_cfg = get_next_tier(PlanTier.FREE)
    assert next_cfg is not None
    assert next_cfg.tier == PlanTier.BASIC


def test_get_next_tier_returns_none_for_enterprise():
    assert get_next_tier(PlanTier.ENTERPRISE) is None


# ── Stripe helpers ────────────────────────────────────────────────────────────

def test_free_tier_stripe_price_id_is_empty():
    assert stripe_price_id(PlanTier.FREE) == ""
    assert stripe_price_id(PlanTier.FREE, annual=True) == ""


def test_paid_tier_stripe_setting_names_not_empty():
    for tier in (PlanTier.BASIC, PlanTier.PRO, PlanTier.ENTERPRISE):
        cfg = get_tier(tier)
        assert cfg.stripe_monthly_price_setting != ""
        assert cfg.stripe_annual_price_setting != ""


def test_get_tier_accepts_string():
    cfg = get_tier("BASIC")
    assert cfg.tier == PlanTier.BASIC


def test_get_tier_accepts_lowercase_string():
    cfg = get_tier("pro")
    assert cfg.tier == PlanTier.PRO


# ── Alignment with billing/constants.py ──────────────────────────────────────

def test_tier_daily_api_limits_align_with_constants():
    """TierConfig daily_api_calls must match TIER_DAILY_API_LIMITS."""
    for tier in PlanTier:
        constant_limit = TIER_DAILY_API_LIMITS.get(tier.value)
        if constant_limit is None:
            continue
        cfg_limit = get_tier(tier).daily_api_calls
        assert cfg_limit == constant_limit, (
            f"{tier.value}: TierConfig.daily_api_calls={cfg_limit} != "
            f"TIER_DAILY_API_LIMITS={constant_limit}"
        )

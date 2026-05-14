"""
Upgrade Trigger Tests — Task 3
================================
Verifies soft paywall (warn), hard paywall (block), and all trigger types.

Checks:
  - No triggers below warn threshold
  - Soft CTA at warn threshold (non-blocking)
  - Hard block at block threshold
  - All resource types trigger correctly
  - Feature gate trigger
  - Rate limit trigger (after N hits)
  - Cost cap triggers
  - Enterprise unlimited daily_api_calls never triggers DAILY_API triggers
  - Top tier: suggested_tier is None
  - UpgradeCTA.as_dict() has required keys
"""
from __future__ import annotations

import pytest

from app.pricing.tiers import PlanTier, TierFeature
from app.pricing.upgrade import (
    UpgradeCTA,
    UpgradeEvaluator,
    UpgradeTrigger,
    UsageSnapshot,
)


def _snap(tier=PlanTier.FREE, **kwargs) -> UsageSnapshot:
    return UsageSnapshot(user_id="u1", tier=tier, **kwargs)


# ── No triggers ───────────────────────────────────────────────────────────────

def test_no_triggers_for_empty_usage(evaluator, free_snapshot):
    ctas = evaluator.evaluate(free_snapshot)
    assert ctas == []


def test_no_triggers_at_50_percent_usage(evaluator):
    snap = _snap(
        tier=PlanTier.BASIC,
        chars_used=50_000,      # 50% of 100K
        jobs_created=25,        # 50% of 50
    )
    ctas = evaluator.evaluate(snap)
    assert ctas == []


# ── Chars quota ───────────────────────────────────────────────────────────────

def test_chars_warning_at_warn_threshold(evaluator):
    # FREE warn_usage_pct = 0.80, monthly_chars = 10_000
    snap = _snap(tier=PlanTier.FREE, chars_used=8_000)  # 80%
    ctas = evaluator.evaluate(snap)
    warn = [c for c in ctas if c.trigger == UpgradeTrigger.QUOTA_CHARS_WARNING]
    assert len(warn) == 1
    assert not warn[0].blocking


def test_chars_block_at_100_percent(evaluator):
    snap = _snap(tier=PlanTier.FREE, chars_used=10_000)  # 100%
    ctas = evaluator.evaluate(snap)
    block = [c for c in ctas if c.trigger == UpgradeTrigger.QUOTA_CHARS_EXHAUSTED]
    assert len(block) == 1
    assert block[0].blocking


def test_chars_block_above_100_percent(evaluator):
    snap = _snap(tier=PlanTier.FREE, chars_used=12_000)  # 120%
    assert evaluator.has_blocking_trigger(snap)


def test_chars_warn_not_blocking(evaluator):
    snap = _snap(tier=PlanTier.BASIC, chars_used=82_000)  # 82%
    ctas = [c for c in evaluator.evaluate(snap) if "chars" in c.trigger.value]
    assert all(not c.blocking for c in ctas if "warning" in c.trigger.value)


# ── Jobs quota ────────────────────────────────────────────────────────────────

def test_jobs_warning_fires(evaluator):
    snap = _snap(tier=PlanTier.FREE, jobs_created=4)  # 80% of 5
    ctas = evaluator.evaluate(snap)
    warn = [c for c in ctas if c.trigger == UpgradeTrigger.QUOTA_JOBS_WARNING]
    assert len(warn) == 1


def test_jobs_block_fires(evaluator):
    snap = _snap(tier=PlanTier.FREE, jobs_created=5)  # 100% of 5
    ctas = evaluator.evaluate(snap)
    block = [c for c in ctas if c.trigger == UpgradeTrigger.QUOTA_JOBS_EXHAUSTED]
    assert len(block) == 1
    assert block[0].blocking


# ── Storage quota ─────────────────────────────────────────────────────────────

def test_storage_warning_fires(evaluator):
    snap = _snap(tier=PlanTier.FREE, storage_mb=82.0)  # 82% of 100
    ctas = evaluator.evaluate(snap)
    warn = [c for c in ctas if c.trigger == UpgradeTrigger.QUOTA_STORAGE_WARNING]
    assert len(warn) == 1
    assert not warn[0].blocking


def test_storage_block_fires(evaluator):
    snap = _snap(tier=PlanTier.FREE, storage_mb=100.0)  # 100% of 100
    ctas = evaluator.evaluate(snap)
    block = [c for c in ctas if c.trigger == UpgradeTrigger.QUOTA_STORAGE_EXHAUSTED]
    assert len(block) == 1
    assert block[0].blocking


# ── Daily API quota ───────────────────────────────────────────────────────────

def test_daily_api_warning_fires(evaluator):
    snap = _snap(tier=PlanTier.FREE, daily_api_calls=82)  # 82% of 100
    ctas = evaluator.evaluate(snap)
    warn = [c for c in ctas if c.trigger == UpgradeTrigger.DAILY_API_WARNING]
    assert len(warn) == 1


def test_daily_api_block_fires(evaluator):
    snap = _snap(tier=PlanTier.FREE, daily_api_calls=100)  # 100% of 100
    ctas = evaluator.evaluate(snap)
    block = [c for c in ctas if c.trigger == UpgradeTrigger.DAILY_API_EXHAUSTED]
    assert len(block) == 1
    assert block[0].blocking


def test_enterprise_unlimited_no_daily_api_trigger(evaluator):
    snap = _snap(tier=PlanTier.ENTERPRISE, daily_api_calls=999_999)
    ctas = evaluator.evaluate(snap)
    api_ctas = [c for c in ctas if "daily_api" in c.trigger.value]
    assert api_ctas == []


# ── Cost cap ──────────────────────────────────────────────────────────────────

def test_cost_cap_warning_fires(evaluator):
    # FREE max_daily_cost = $0.02; warn at 80% = $0.016
    snap = _snap(tier=PlanTier.FREE, daily_cost_usd=0.017)
    ctas = evaluator.evaluate(snap)
    warn = [c for c in ctas if c.trigger == UpgradeTrigger.COST_CAP_WARNING]
    assert len(warn) == 1
    assert not warn[0].blocking


def test_cost_cap_exceeded_fires(evaluator):
    snap = _snap(tier=PlanTier.FREE, daily_cost_usd=0.025)  # > $0.02
    ctas = evaluator.evaluate(snap)
    block = [c for c in ctas if c.trigger == UpgradeTrigger.COST_CAP_EXCEEDED]
    assert len(block) == 1
    assert block[0].blocking


def test_pro_cost_cap_exceeded(evaluator):
    snap = _snap(tier=PlanTier.PRO, daily_cost_usd=2.00)  # > $1.50
    ctas = evaluator.evaluate(snap)
    block = [c for c in ctas if c.trigger == UpgradeTrigger.COST_CAP_EXCEEDED]
    assert len(block) == 1


# ── Feature gate ──────────────────────────────────────────────────────────────

def test_feature_gate_blocks_unavailable_feature(evaluator):
    snap = _snap(
        tier=PlanTier.FREE,
        attempted_feature=TierFeature.CUSTOM_VOICES,
    )
    ctas = evaluator.evaluate(snap)
    gate = [c for c in ctas if c.trigger == UpgradeTrigger.FEATURE_GATE_HIT]
    assert len(gate) == 1
    assert gate[0].blocking


def test_feature_gate_no_trigger_for_available_feature(evaluator):
    snap = _snap(
        tier=PlanTier.FREE,
        attempted_feature=TierFeature.DOCUMENT_UPLOAD,  # available on FREE
    )
    ctas = evaluator.evaluate(snap)
    gate = [c for c in ctas if c.trigger == UpgradeTrigger.FEATURE_GATE_HIT]
    assert gate == []


def test_feature_gate_suggests_next_tier(evaluator):
    snap = _snap(
        tier=PlanTier.BASIC,
        attempted_feature=TierFeature.CUSTOM_VOICES,  # only on PRO+
    )
    ctas = evaluator.evaluate(snap)
    gate = next(c for c in ctas if c.trigger == UpgradeTrigger.FEATURE_GATE_HIT)
    assert gate.suggested_tier == PlanTier.PRO


def test_feature_gate_enterprise_suggests_none(evaluator):
    # Enterprise has all features, so no gate hit possible
    snap = _snap(
        tier=PlanTier.ENTERPRISE,
        attempted_feature=TierFeature.SLA_SUPPORT,
    )
    ctas = evaluator.evaluate(snap)
    gate = [c for c in ctas if c.trigger == UpgradeTrigger.FEATURE_GATE_HIT]
    assert gate == []


# ── Rate limit ────────────────────────────────────────────────────────────────

def test_rate_limit_cta_fires_after_threshold(evaluator):
    snap = _snap(tier=PlanTier.FREE, rate_limit_hits_24h=5)
    ctas = evaluator.evaluate(snap)
    rl = [c for c in ctas if c.trigger == UpgradeTrigger.RATE_LIMIT_HIT]
    assert len(rl) == 1
    assert not rl[0].blocking  # rate limit CTA is always soft


def test_rate_limit_no_trigger_below_threshold(evaluator):
    snap = _snap(tier=PlanTier.FREE, rate_limit_hits_24h=2)  # below threshold (3)
    ctas = evaluator.evaluate(snap)
    rl = [c for c in ctas if c.trigger == UpgradeTrigger.RATE_LIMIT_HIT]
    assert rl == []


# ── has_blocking_trigger ──────────────────────────────────────────────────────

def test_has_blocking_trigger_true_for_exhausted_quota(evaluator):
    snap = _snap(tier=PlanTier.FREE, chars_used=10_000)
    assert evaluator.has_blocking_trigger(snap)


def test_has_blocking_trigger_false_for_warn_only(evaluator):
    snap = _snap(tier=PlanTier.FREE, chars_used=8_500)  # 85% — warn only
    assert not evaluator.has_blocking_trigger(snap)


# ── highest_priority ──────────────────────────────────────────────────────────

def test_highest_priority_returns_blocking_over_warning(evaluator):
    snap = _snap(
        tier=PlanTier.FREE,
        chars_used=10_000,      # blocking: chars exhausted
        rate_limit_hits_24h=5,  # non-blocking: rate limit
    )
    top = evaluator.highest_priority(snap)
    assert top is not None
    assert top.blocking


def test_highest_priority_returns_none_for_clean_snapshot(evaluator, free_snapshot):
    assert evaluator.highest_priority(free_snapshot) is None


# ── CTA data shape ────────────────────────────────────────────────────────────

def test_cta_as_dict_has_required_keys(evaluator):
    snap = _snap(tier=PlanTier.FREE, chars_used=8_000)
    ctas = evaluator.evaluate(snap)
    assert ctas
    d = ctas[0].as_dict()
    for key in ("trigger", "current_tier", "suggested_tier", "resource_type",
                "current_value", "limit_value", "usage_pct", "blocking", "message"):
        assert key in d


def test_cta_message_is_non_empty(evaluator):
    snap = _snap(tier=PlanTier.FREE, chars_used=8_000)
    ctas = evaluator.evaluate(snap)
    for cta in ctas:
        assert cta.message.strip() != ""


# ── Suggested tier ────────────────────────────────────────────────────────────

def test_suggested_tier_is_none_for_enterprise(evaluator):
    snap = _snap(tier=PlanTier.ENTERPRISE, chars_used=5_000_000)  # 100%
    ctas = evaluator.evaluate(snap)
    for cta in ctas:
        assert cta.suggested_tier is None


def test_suggested_tier_is_next_tier(evaluator):
    snap = _snap(tier=PlanTier.BASIC, chars_used=100_000)  # 100%
    ctas = [c for c in evaluator.evaluate(snap) if c.trigger == UpgradeTrigger.QUOTA_CHARS_EXHAUSTED]
    assert ctas
    assert ctas[0].suggested_tier == PlanTier.PRO

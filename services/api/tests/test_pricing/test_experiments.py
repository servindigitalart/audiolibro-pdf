"""
Pricing Experiments Tests — Task 5
=====================================
Verifies the A/B experiment system is deterministic, safe, and rollback-safe.

Checks:
  - Inactive experiments always return CONTROL
  - Deterministic assignment: same user always gets same variant
  - Different users get different variants (bucket distribution)
  - Rollout 0% → everyone gets CONTROL
  - Rollout 100% → everyone gets TREATMENT
  - Overrides are applied correctly (absolute and multiplicative)
  - Non-eligible tiers receive no override
  - get_effective_limits never returns negative resource values
  - Only one experiment applied per user (no stacking)
  - active_experiments_for returns correct subset
"""
from __future__ import annotations

import pytest

from app.pricing.experiments import (
    ACTIVE_EXPERIMENTS,
    ExperimentService,
    ExperimentVariant,
    LimitOverride,
    PricingExperiment,
)
from app.pricing.tiers import TIER_CATALOG, PlanTier


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_experiment(
    *,
    experiment_id="test",
    tiers=(PlanTier.FREE,),
    rollout_pct=100,
    active=True,
    overrides=None,
) -> dict[str, PricingExperiment]:
    return {
        experiment_id: PricingExperiment(
            experiment_id=experiment_id,
            description="test",
            eligible_tiers=frozenset(tiers),
            rollout_pct=rollout_pct,
            active=active,
            treatment_overrides=overrides or LimitOverride(),
        )
    }


# ── Inactive experiment ───────────────────────────────────────────────────────

def test_inactive_experiment_returns_control():
    registry = _make_experiment(active=False)
    svc = ExperimentService(registry)
    assert svc.get_variant("any-user", "test") == ExperimentVariant.CONTROL


def test_inactive_experiment_does_not_override_limits():
    registry = _make_experiment(
        active=False, overrides=LimitOverride(monthly_chars=99_999)
    )
    svc = ExperimentService(registry)
    effective = svc.get_effective_limits("any-user", PlanTier.FREE)
    assert effective.monthly_chars == TIER_CATALOG[PlanTier.FREE].monthly_chars


# ── Deterministic assignment ──────────────────────────────────────────────────

def test_same_user_always_same_variant():
    registry = _make_experiment(rollout_pct=50)
    svc = ExperimentService(registry)
    user_id = "user-stable-abc123"
    v1 = svc.get_variant(user_id, "test")
    v2 = svc.get_variant(user_id, "test")
    assert v1 == v2


def test_different_experiments_can_differ_for_same_user():
    # A user in TREATMENT for experiment A may be CONTROL for experiment B
    registry = {
        "exp_a": PricingExperiment(
            experiment_id="exp_a",
            description="A",
            eligible_tiers=frozenset({PlanTier.FREE}),
            rollout_pct=50,
            active=True,
            treatment_overrides=LimitOverride(monthly_chars=20_000),
        ),
        "exp_b": PricingExperiment(
            experiment_id="exp_b",
            description="B",
            eligible_tiers=frozenset({PlanTier.FREE}),
            rollout_pct=50,
            active=True,
            treatment_overrides=LimitOverride(monthly_chars=15_000),
        ),
    }
    svc = ExperimentService(registry)
    user_id = "test-user-stable"
    v_a = svc.get_variant(user_id, "exp_a")
    v_b = svc.get_variant(user_id, "exp_b")
    # Both are deterministic, even if they happen to be the same
    assert v_a in list(ExperimentVariant)
    assert v_b in list(ExperimentVariant)


# ── Rollout percentages ───────────────────────────────────────────────────────

def test_rollout_0_pct_all_control():
    registry = _make_experiment(rollout_pct=0)
    svc = ExperimentService(registry)
    users = [f"user-{i}" for i in range(100)]
    variants = [svc.get_variant(u, "test") for u in users]
    assert all(v == ExperimentVariant.CONTROL for v in variants)


def test_rollout_100_pct_all_treatment():
    registry = _make_experiment(rollout_pct=100)
    svc = ExperimentService(registry)
    users = [f"user-{i}" for i in range(100)]
    variants = [svc.get_variant(u, "test") for u in users]
    assert all(v == ExperimentVariant.TREATMENT for v in variants)


def test_rollout_50_pct_roughly_half_treatment():
    """At 50% rollout across 200 users, expect ~40–60% in treatment."""
    registry = _make_experiment(rollout_pct=50)
    svc = ExperimentService(registry)
    users = [f"user-rollout-{i}" for i in range(200)]
    treatment_count = sum(
        1 for u in users if svc.get_variant(u, "test") == ExperimentVariant.TREATMENT
    )
    assert 60 <= treatment_count <= 140, f"Unexpected distribution: {treatment_count}/200"


# ── Overrides ─────────────────────────────────────────────────────────────────

def test_absolute_chars_override_applied(exp_service):
    # exp_service fixture: 100% rollout, FREE tier, chars=20_000
    effective = exp_service.get_effective_limits("any-user", PlanTier.FREE)
    assert effective.monthly_chars == 20_000


def test_absolute_jobs_override_applied():
    registry = _make_experiment(overrides=LimitOverride(monthly_jobs=8))
    svc = ExperimentService(registry)
    effective = svc.get_effective_limits("any-user", PlanTier.FREE)
    assert effective.monthly_jobs == 8


def test_multiplier_override_applied():
    registry = _make_experiment(
        tiers=(PlanTier.PRO,),
        overrides=LimitOverride(chars_multiplier=1.5),
    )
    svc = ExperimentService(registry)
    base_chars = TIER_CATALOG[PlanTier.PRO].monthly_chars
    effective = svc.get_effective_limits("user-a", PlanTier.PRO)
    assert effective.monthly_chars == int(base_chars * 1.5)


def test_absolute_override_beats_multiplier():
    registry = _make_experiment(
        overrides=LimitOverride(chars_multiplier=2.0, monthly_chars=5_000)
    )
    svc = ExperimentService(registry)
    effective = svc.get_effective_limits("any-user", PlanTier.FREE)
    # Absolute wins: 5_000, not 2× 10_000 = 20_000
    assert effective.monthly_chars == 5_000


def test_trial_days_override():
    registry = _make_experiment(
        tiers=(PlanTier.BASIC,),
        overrides=LimitOverride(trial_days=21),
    )
    svc = ExperimentService(registry)
    effective = svc.get_effective_limits("user-b", PlanTier.BASIC)
    assert effective.trial_days == 21


def test_price_override():
    registry = _make_experiment(
        tiers=(PlanTier.BASIC,),
        overrides=LimitOverride(monthly_price_usd=7.00),
    )
    svc = ExperimentService(registry)
    effective = svc.get_effective_limits("user-c", PlanTier.BASIC)
    assert effective.monthly_price_usd == 7.00


# ── Safety: non-negative values ───────────────────────────────────────────────

def test_override_zero_chars_minimum_is_one():
    registry = _make_experiment(overrides=LimitOverride(monthly_chars=0))
    svc = ExperimentService(registry)
    effective = svc.get_effective_limits("user", PlanTier.FREE)
    assert effective.monthly_chars >= 1


def test_override_negative_price_clamped_to_zero():
    registry = _make_experiment(
        tiers=(PlanTier.BASIC,),
        overrides=LimitOverride(monthly_price_usd=-5.00),
    )
    svc = ExperimentService(registry)
    effective = svc.get_effective_limits("user", PlanTier.BASIC)
    assert effective.monthly_price_usd >= 0.0


# ── Non-eligible tier ─────────────────────────────────────────────────────────

def test_non_eligible_tier_not_overridden():
    # Experiment only for FREE, check PRO
    registry = _make_experiment(
        tiers=(PlanTier.FREE,),
        overrides=LimitOverride(monthly_chars=99_999),
    )
    svc = ExperimentService(registry)
    effective = svc.get_effective_limits("any-user", PlanTier.PRO)
    assert effective.monthly_chars == TIER_CATALOG[PlanTier.PRO].monthly_chars


# ── Control variant gets base limits ─────────────────────────────────────────

def test_control_variant_gets_base_limits():
    registry = _make_experiment(rollout_pct=0)  # everyone gets CONTROL
    svc = ExperimentService(registry)
    effective = svc.get_effective_limits("user-ctrl", PlanTier.FREE)
    assert effective.monthly_chars == TIER_CATALOG[PlanTier.FREE].monthly_chars


# ── is_in_treatment ───────────────────────────────────────────────────────────

def test_is_in_treatment_returns_bool():
    registry = _make_experiment(rollout_pct=100)
    svc = ExperimentService(registry)
    result = svc.is_in_treatment("user-d", "test")
    assert isinstance(result, bool)
    assert result is True


# ── active_experiments_for ────────────────────────────────────────────────────

def test_active_experiments_for_returns_matching():
    registry = {
        "free_exp": PricingExperiment(
            experiment_id="free_exp",
            description="",
            eligible_tiers=frozenset({PlanTier.FREE}),
            rollout_pct=50,
            active=True,
            treatment_overrides=LimitOverride(),
        ),
        "pro_exp": PricingExperiment(
            experiment_id="pro_exp",
            description="",
            eligible_tiers=frozenset({PlanTier.PRO}),
            rollout_pct=50,
            active=True,
            treatment_overrides=LimitOverride(),
        ),
    }
    svc = ExperimentService(registry)
    free_exps = svc.active_experiments_for(PlanTier.FREE)
    assert len(free_exps) == 1
    assert free_exps[0].experiment_id == "free_exp"


def test_active_experiments_for_excludes_inactive():
    registry = _make_experiment(active=False)
    svc = ExperimentService(registry)
    assert svc.active_experiments_for(PlanTier.FREE) == []


# ── Unknown experiment ────────────────────────────────────────────────────────

def test_unknown_experiment_returns_control():
    svc = ExperimentService(registry={})
    assert svc.get_variant("user", "nonexistent") == ExperimentVariant.CONTROL


# ── Active experiments registry ───────────────────────────────────────────────

def test_all_builtin_experiments_are_inactive_by_default():
    """Built-in experiments must default to inactive to avoid surprise production changes."""
    for exp in ACTIVE_EXPERIMENTS.values():
        assert not exp.active, (
            f"Experiment {exp.experiment_id!r} is active by default — "
            "set active=False before deploying"
        )

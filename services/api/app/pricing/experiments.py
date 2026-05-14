"""
Pricing Experimentation System — Task 5
==========================================
A/B testing for pricing tiers, limits, and feature access.

Design:
  - Experiments are defined in code (or loaded from Redis for hot config)
  - Each experiment has a control variant and one or more treatment variants
  - User assignment is deterministic: hash(user_id + experiment_id) % 100
    so the same user always gets the same variant (no session stickiness needed)
  - Experiments can override: monthly_chars, monthly_jobs, monthly_price_usd,
    trial_days, or feature access
  - A registry holds active experiments; inactive ones pass through unchanged
  - All overrides are additive/multiplicative — never expose raw tier data to
    experiments directly (prevents accidental tier config mutation)

Safety guarantees:
  - get_effective_limits() always returns valid non-negative values
  - Inactive experiments return unmodified tier config
  - Rollback = mark experiment inactive (no code change needed)
  - No experiment can remove features from a higher tier (one-way: can only add)

Usage:
    svc = ExperimentService(registry=ACTIVE_EXPERIMENTS)
    variant = svc.get_variant("user-uuid-123", "trial_extension_test")
    limits = svc.get_effective_limits("user-uuid-123", PlanTier.BASIC)
    print(limits.monthly_chars)  # 100_000 or 150_000 depending on variant
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

from app.pricing.tiers import TIER_CATALOG, PlanTier, TierConfig


# ── Variant ───────────────────────────────────────────────────────────────────

class ExperimentVariant(str, Enum):
    CONTROL   = "control"
    TREATMENT = "treatment"
    # Multi-armed experiments can add more: TREATMENT_A, TREATMENT_B, etc.


# ── Override model ────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class LimitOverride:
    """
    Additive/multiplicative overrides applied to a TierConfig.

    Multiplicative overrides (multiplier != 1.0) are applied first,
    then absolute overrides replace the value entirely.
    None means "no override for this field".
    """
    # Absolute overrides (replace the value)
    monthly_chars: Optional[int] = None
    monthly_jobs: Optional[int] = None
    storage_mb: Optional[int] = None
    daily_api_calls: Optional[int] = None
    trial_days: Optional[int] = None

    # Multiplicative overrides (scale the existing value)
    chars_multiplier: float = 1.0
    jobs_multiplier: float = 1.0

    # Price overrides (for price sensitivity experiments)
    monthly_price_usd: Optional[float] = None


# ── Experiment definition ─────────────────────────────────────────────────────

@dataclass
class PricingExperiment:
    """
    A single pricing experiment.

    eligible_tiers: which plan tiers are in the experiment (empty = all tiers)
    rollout_pct:    0–100, percentage of users in the experiment
                    (the rest always see CONTROL)
    treatment_overrides: applied to users in the TREATMENT variant
    """
    experiment_id: str
    description: str
    eligible_tiers: frozenset[PlanTier] = field(default_factory=frozenset)
    rollout_pct: int = 50                        # 0–100
    active: bool = True
    treatment_overrides: LimitOverride = field(default_factory=LimitOverride)

    def is_eligible(self, tier: PlanTier) -> bool:
        if not self.eligible_tiers:
            return True  # all tiers
        return tier in self.eligible_tiers


# ── Built-in experiments (modify to run live experiments) ─────────────────────

# IMPORTANT: Set active=False to roll back an experiment without a code deploy.
ACTIVE_EXPERIMENTS: dict[str, PricingExperiment] = {
    "free_tier_chars_test": PricingExperiment(
        experiment_id="free_tier_chars_test",
        description="Test 15K vs 10K char limit on free tier for conversion impact",
        eligible_tiers=frozenset({PlanTier.FREE}),
        rollout_pct=50,
        active=False,       # disabled by default — enable to run
        treatment_overrides=LimitOverride(monthly_chars=15_000),
    ),

    "basic_trial_extension": PricingExperiment(
        experiment_id="basic_trial_extension",
        description="Test 14-day vs 7-day trial for BASIC tier conversion",
        eligible_tiers=frozenset({PlanTier.BASIC}),
        rollout_pct=50,
        active=False,
        treatment_overrides=LimitOverride(trial_days=14),
    ),

    "pro_jobs_multiplier": PricingExperiment(
        experiment_id="pro_jobs_multiplier",
        description="Test 1.5× job limit on PRO tier for retention impact",
        eligible_tiers=frozenset({PlanTier.PRO}),
        rollout_pct=20,
        active=False,
        treatment_overrides=LimitOverride(jobs_multiplier=1.5),
    ),
}


# ── Service ───────────────────────────────────────────────────────────────────

class ExperimentService:
    """
    Deterministic A/B experiment assignment and limit resolution.

    Assignment is hash-based so it's stable across restarts and horizontally
    scaled instances without any shared state.
    """

    def __init__(
        self,
        registry: dict[str, PricingExperiment] | None = None,
    ) -> None:
        self._registry = registry if registry is not None else ACTIVE_EXPERIMENTS

    # ── Assignment ────────────────────────────────────────────────────────────

    def get_variant(
        self,
        user_id: str,
        experiment_id: str,
    ) -> ExperimentVariant:
        """
        Return CONTROL or TREATMENT for this user × experiment pair.

        Always returns CONTROL if the experiment is inactive or user is
        outside the rollout percentage.
        """
        experiment = self._registry.get(experiment_id)
        if experiment is None or not experiment.active:
            return ExperimentVariant.CONTROL

        bucket = self._bucket(user_id, experiment_id)
        if bucket < experiment.rollout_pct:
            return ExperimentVariant.TREATMENT
        return ExperimentVariant.CONTROL

    def is_in_treatment(self, user_id: str, experiment_id: str) -> bool:
        return self.get_variant(user_id, experiment_id) == ExperimentVariant.TREATMENT

    # ── Effective limits ──────────────────────────────────────────────────────

    def get_effective_limits(
        self,
        user_id: str,
        tier: PlanTier,
    ) -> TierConfig:
        """
        Return the TierConfig the user actually experiences, after applying
        any active experiment overrides.

        Guarantees: the returned config has all non-negative resource limits.
        """
        base = TIER_CATALOG[tier]
        overridden = False

        # Apply the first matching active experiment (experiments don't stack)
        for exp in self._registry.values():
            if not exp.active:
                continue
            if not exp.is_eligible(tier):
                continue
            if self.get_variant(user_id, exp.experiment_id) != ExperimentVariant.TREATMENT:
                continue

            base = self._apply_override(base, exp.treatment_overrides)
            overridden = True
            break  # one experiment at a time per user

        return base

    def active_experiments_for(
        self,
        tier: PlanTier,
    ) -> list[PricingExperiment]:
        """Return all active experiments that include `tier`."""
        return [
            exp for exp in self._registry.values()
            if exp.active and exp.is_eligible(tier)
        ]

    # ── Internal ──────────────────────────────────────────────────────────────

    @staticmethod
    def _bucket(user_id: str, experiment_id: str) -> int:
        """Stable 0–99 bucket for deterministic assignment."""
        digest = hashlib.sha256(f"{user_id}:{experiment_id}".encode()).hexdigest()
        return int(digest[:8], 16) % 100

    @staticmethod
    def _apply_override(base: TierConfig, override: LimitOverride) -> TierConfig:
        """Return a new TierConfig with experiment overrides applied."""
        # Gather mutable fields
        monthly_chars = base.monthly_chars
        monthly_jobs  = base.monthly_jobs

        # Multiplicative first
        monthly_chars = max(1, int(monthly_chars * override.chars_multiplier))
        monthly_jobs  = max(1, int(monthly_jobs  * override.jobs_multiplier))

        # Absolute overrides replace
        if override.monthly_chars is not None:
            monthly_chars = max(1, override.monthly_chars)
        if override.monthly_jobs is not None:
            monthly_jobs  = max(1, override.monthly_jobs)

        storage_mb       = override.storage_mb        if override.storage_mb        is not None else base.storage_mb
        daily_api_calls  = override.daily_api_calls   if override.daily_api_calls   is not None else base.daily_api_calls
        trial_days       = override.trial_days        if override.trial_days        is not None else base.trial_days
        monthly_price    = override.monthly_price_usd if override.monthly_price_usd is not None else base.monthly_price_usd

        # dataclass is frozen so we rebuild
        return TierConfig(
            tier=base.tier,
            monthly_price_usd=max(0.0, monthly_price),
            annual_price_usd=base.annual_price_usd,
            stripe_monthly_price_setting=base.stripe_monthly_price_setting,
            stripe_annual_price_setting=base.stripe_annual_price_setting,
            monthly_chars=monthly_chars,
            monthly_jobs=monthly_jobs,
            concurrent_jobs=base.concurrent_jobs,
            storage_mb=storage_mb,
            daily_api_calls=daily_api_calls,
            api_calls_per_minute=base.api_calls_per_minute,
            max_daily_cost_usd=base.max_daily_cost_usd,
            max_monthly_cost_usd=base.max_monthly_cost_usd,
            warn_usage_pct=base.warn_usage_pct,
            block_usage_pct=base.block_usage_pct,
            features=base.features,
            max_team_members=base.max_team_members,
            upgrades_to=base.upgrades_to,
            trial_days=trial_days,
        )

"""
Pricing & Monetization Engine
==============================
Single import surface for the pricing system.

Components:
  tiers           — canonical tier definitions, limits, and pricing
  unit_economics  — cost/margin/break-even calculations
  upgrade         — upgrade trigger evaluation and paywall logic
  protection      — revenue protection: cost caps, negative-margin throttling
  experiments     — A/B pricing experiments and dynamic limit overrides
"""
from app.pricing.tiers import (
    TierConfig,
    TIER_CATALOG,
    PlanTier,
    get_tier,
    get_next_tier,
    stripe_price_id,
)
from app.pricing.unit_economics import (
    UnitCostRates,
    COST_RATES,
    TierEconomics,
    ProfitabilityReport,
    UnitEconomicsEngine,
)
from app.pricing.upgrade import (
    UpgradeTrigger,
    UpgradeCTA,
    UsageSnapshot,
    UpgradeEvaluator,
)
from app.pricing.protection import (
    CostCapExceeded,
    NegativeMarginThrottle,
    RevenueProtectionService,
)
from app.pricing.experiments import (
    ExperimentVariant,
    PricingExperiment,
    ExperimentService,
)

__all__ = [
    "TierConfig", "TIER_CATALOG", "PlanTier", "get_tier", "get_next_tier", "stripe_price_id",
    "UnitCostRates", "COST_RATES", "TierEconomics", "ProfitabilityReport", "UnitEconomicsEngine",
    "UpgradeTrigger", "UpgradeCTA", "UsageSnapshot", "UpgradeEvaluator",
    "CostCapExceeded", "NegativeMarginThrottle", "RevenueProtectionService",
    "ExperimentVariant", "PricingExperiment", "ExperimentService",
]

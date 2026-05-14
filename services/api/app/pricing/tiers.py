"""
Pricing Tiers — Canonical Tier Registry
=========================================
Single source of truth for ALL tier-level configuration:
  - Monthly and annual prices
  - Resource limits (chars, jobs, storage, API calls)
  - Internal cost caps (prevent negative-margin users)
  - Feature access via feature flag names
  - Rate limit parameters
  - Stripe price ID lookup
  - Upgrade path

Design contract:
  - NEVER duplicate resource limits already in financial/quota/quota_limits.py;
    instead, TierConfig carries the *billing* dimension and references quota limits.
  - billing/constants.py TIER_DAILY_API_LIMITS remain the enforcement source;
    TierConfig.daily_api_calls must be kept in sync.
  - Stripe price IDs are resolved at runtime from settings so they are
    environment-specific (test/staging/prod use different IDs).

Usage:
    tier = get_tier(PlanTier.PRO)
    print(tier.monthly_price_usd)       # 29.00
    print(tier.max_daily_cost_usd)      # 1.50
    price_id = stripe_price_id(PlanTier.PRO, annual=False)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import FrozenSet, Optional

from app.core.config import settings


# ── Tier enum ─────────────────────────────────────────────────────────────────
# Values intentionally uppercase to match billing/constants.py and DB plan_tier column

class PlanTier(str, Enum):
    FREE       = "FREE"
    BASIC      = "BASIC"
    PRO        = "PRO"
    ENTERPRISE = "ENTERPRISE"


# ── Feature keys ─────────────────────────────────────────────────────────────

class TierFeature(str, Enum):
    DOCUMENT_UPLOAD      = "document_upload"
    TTS_PROCESSING       = "tts_processing"
    PRIORITY_PROCESSING  = "priority_processing"
    CUSTOM_VOICES        = "custom_voices"
    API_ACCESS           = "api_access"
    TEAM_MEMBERS         = "team_members"
    ADVANCED_ANALYTICS   = "advanced_analytics"
    SLA_SUPPORT          = "sla_support"
    CUSTOM_INTEGRATION   = "custom_integration"
    WEBHOOK_CALLBACKS    = "webhook_callbacks"


# ── Tier configuration ────────────────────────────────────────────────────────

@dataclass(frozen=True)
class TierConfig:
    """
    Complete billing + product configuration for one pricing tier.

    Resource limits here are the enforced values.  They must match
    the corresponding financial/quota/quota_limits.py PLAN_QUOTAS entry.
    """

    tier: PlanTier

    # ── Pricing ───────────────────────────────────────────────────────────────
    monthly_price_usd: float
    annual_price_usd: float          # full annual charge (typically 20% off ×12)

    # Stripe settings attribute names (resolved at runtime via settings)
    stripe_monthly_price_setting: str   # e.g. "stripe_price_basic_monthly"
    stripe_annual_price_setting: str    # e.g. "stripe_price_basic_yearly"

    # ── Resource limits ───────────────────────────────────────────────────────
    monthly_chars: int                  # TTS characters/month
    monthly_jobs: int                   # conversion jobs/month
    concurrent_jobs: int                # jobs running simultaneously
    storage_mb: int                     # persistent storage cap
    daily_api_calls: int                # -1 = unlimited (mirrors TIER_DAILY_API_LIMITS)
    api_calls_per_minute: int           # burst rate cap

    # ── Internal cost caps (protect margin) ───────────────────────────────────
    max_daily_cost_usd: float           # hard cap: block if exceeded in 24h
    max_monthly_cost_usd: float         # hard cap: block if exceeded in billing month

    # ── Soft-paywall thresholds ───────────────────────────────────────────────
    warn_usage_pct: float = 0.80        # CTA shown when this fraction of quota is used
    block_usage_pct: float = 1.00       # hard block at this fraction

    # ── Features ──────────────────────────────────────────────────────────────
    features: FrozenSet[TierFeature] = field(default_factory=frozenset)
    max_team_members: int = 1

    # ── Upgrade path ──────────────────────────────────────────────────────────
    upgrades_to: Optional[PlanTier] = None  # None means top tier

    # ── Trial eligibility ─────────────────────────────────────────────────────
    trial_days: int = 0


# ── Tier catalog ──────────────────────────────────────────────────────────────
# These numbers reflect Google Cloud Neural2 TTS at $0.000016/char as primary cost.
# See unit_economics.py for full margin breakdown.

TIER_CATALOG: dict[PlanTier, TierConfig] = {

    PlanTier.FREE: TierConfig(
        tier=PlanTier.FREE,
        monthly_price_usd=0.00,
        annual_price_usd=0.00,
        stripe_monthly_price_setting="",
        stripe_annual_price_setting="",

        monthly_chars=10_000,           # ~4 pages of text
        monthly_jobs=5,
        concurrent_jobs=1,
        storage_mb=100,
        daily_api_calls=100,
        api_calls_per_minute=10,

        # Cost cap: at $0.000016/char × 10K + infra → max realistic $0.20/month
        max_daily_cost_usd=0.02,        # ~$0.60/month if saturated every day
        max_monthly_cost_usd=0.20,      # absolute monthly ceiling

        warn_usage_pct=0.80,
        block_usage_pct=1.00,

        features=frozenset({
            TierFeature.DOCUMENT_UPLOAD,
            TierFeature.TTS_PROCESSING,
        }),
        max_team_members=1,
        upgrades_to=PlanTier.BASIC,
        trial_days=0,
    ),

    PlanTier.BASIC: TierConfig(
        tier=PlanTier.BASIC,
        monthly_price_usd=9.00,
        annual_price_usd=86.40,         # $7.20/mo × 12 (20% off)
        stripe_monthly_price_setting="stripe_price_basic_monthly",
        stripe_annual_price_setting="stripe_price_basic_yearly",

        monthly_chars=100_000,          # ~40 pages
        monthly_jobs=50,
        concurrent_jobs=2,
        storage_mb=1_000,
        daily_api_calls=1_000,
        api_calls_per_minute=30,

        # TTS cost ceiling: 100K × $0.000016 = $1.60 + infra ≈ $2.00/month
        max_daily_cost_usd=0.25,        # $7.50/month if saturated → still 17% margin
        max_monthly_cost_usd=2.50,

        warn_usage_pct=0.80,
        block_usage_pct=1.00,

        features=frozenset({
            TierFeature.DOCUMENT_UPLOAD,
            TierFeature.TTS_PROCESSING,
            TierFeature.API_ACCESS,
            TierFeature.WEBHOOK_CALLBACKS,
        }),
        max_team_members=1,
        upgrades_to=PlanTier.PRO,
        trial_days=7,
    ),

    PlanTier.PRO: TierConfig(
        tier=PlanTier.PRO,
        monthly_price_usd=29.00,
        annual_price_usd=278.40,        # $23.20/mo × 12 (20% off)
        stripe_monthly_price_setting="stripe_price_pro_monthly",
        stripe_annual_price_setting="stripe_price_pro_yearly",

        monthly_chars=500_000,          # ~200 pages
        monthly_jobs=200,
        concurrent_jobs=5,
        storage_mb=10_000,
        daily_api_calls=10_000,
        api_calls_per_minute=100,

        # TTS ceiling: 500K × $0.000016 = $8.00 + infra ≈ $10/month → 65% margin
        max_daily_cost_usd=1.50,        # $45/month worst-case → still positive
        max_monthly_cost_usd=12.00,

        warn_usage_pct=0.80,
        block_usage_pct=1.00,

        features=frozenset({
            TierFeature.DOCUMENT_UPLOAD,
            TierFeature.TTS_PROCESSING,
            TierFeature.PRIORITY_PROCESSING,
            TierFeature.CUSTOM_VOICES,
            TierFeature.API_ACCESS,
            TierFeature.WEBHOOK_CALLBACKS,
            TierFeature.ADVANCED_ANALYTICS,
        }),
        max_team_members=5,
        upgrades_to=PlanTier.ENTERPRISE,
        trial_days=14,
    ),

    PlanTier.ENTERPRISE: TierConfig(
        tier=PlanTier.ENTERPRISE,
        monthly_price_usd=99.00,
        annual_price_usd=950.40,        # $79.20/mo × 12 (20% off)
        stripe_monthly_price_setting="stripe_price_enterprise_monthly",
        stripe_annual_price_setting="stripe_price_enterprise_yearly",

        monthly_chars=5_000_000,        # ~2000 pages
        monthly_jobs=2_000,
        concurrent_jobs=20,
        storage_mb=100_000,
        daily_api_calls=-1,             # unlimited
        api_calls_per_minute=500,

        # TTS ceiling at 60% avg usage: 3M × $0.000016 = $48 + infra ≈ $55/month → 44% margin
        # Hard cap protects against runaway at 100%: 5M × $0.000016 = $80 → min 4% margin
        max_daily_cost_usd=5.00,        # $150/month budget with daily smoothing
        max_monthly_cost_usd=80.00,     # absolute floor: $99 - $80 = $19 guaranteed

        warn_usage_pct=0.75,            # warn earlier (larger consequence)
        block_usage_pct=0.95,           # soft cap at 95% to preserve margin

        features=frozenset({
            TierFeature.DOCUMENT_UPLOAD,
            TierFeature.TTS_PROCESSING,
            TierFeature.PRIORITY_PROCESSING,
            TierFeature.CUSTOM_VOICES,
            TierFeature.API_ACCESS,
            TierFeature.WEBHOOK_CALLBACKS,
            TierFeature.ADVANCED_ANALYTICS,
            TierFeature.SLA_SUPPORT,
            TierFeature.CUSTOM_INTEGRATION,
            TierFeature.TEAM_MEMBERS,
        }),
        max_team_members=50,
        upgrades_to=None,               # top tier — custom pricing above this
        trial_days=14,
    ),
}


# ── Lookup helpers ────────────────────────────────────────────────────────────

def get_tier(tier: PlanTier | str) -> TierConfig:
    """Return the TierConfig for `tier`.  Accepts enum or string."""
    if isinstance(tier, str):
        tier = PlanTier(tier.upper())
    return TIER_CATALOG[tier]


def get_next_tier(tier: PlanTier | str) -> Optional[TierConfig]:
    """Return the upgrade-target TierConfig, or None if already at top."""
    config = get_tier(tier)
    if config.upgrades_to is None:
        return None
    return TIER_CATALOG[config.upgrades_to]


def has_feature(tier: PlanTier | str, feature: TierFeature) -> bool:
    """Return True if `tier` includes `feature`."""
    return feature in get_tier(tier).features


def stripe_price_id(tier: PlanTier | str, *, annual: bool = False) -> str:
    """
    Resolve the Stripe price ID for `tier` from environment settings.

    Returns an empty string if no price ID is configured (test/free tier).
    """
    config = get_tier(tier)
    attr = config.stripe_annual_price_setting if annual else config.stripe_monthly_price_setting
    if not attr:
        return ""
    return getattr(settings, attr, "") or ""


def effective_daily_api_limit(tier: PlanTier | str) -> int:
    """Return the daily API call limit for enforcement (-1 = unlimited)."""
    return get_tier(tier).daily_api_calls

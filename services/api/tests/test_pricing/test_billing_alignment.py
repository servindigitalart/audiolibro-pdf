"""
Billing Integration Alignment Tests — Task 6
==============================================
Verifies the pricing engine integrates cleanly with the existing billing stack.
No duplication of logic — the pricing engine delegates to the existing components.

Checks:
  - TIER_DAILY_API_LIMITS in billing/constants.py matches TierConfig limits
  - PlanTier.value aligns with billing plan_tier column values (uppercase)
  - TierConfig.monthly_chars matches PLAN_QUOTAS from quota_limits.py
  - Pricing tier names resolve in billing enforcement service
  - SubscriptionStatus states are compatible with pricing access decisions
  - Revenue protection exception types are distinct from billing exceptions
  - guards.enforce_usage_limit uses TIER_DAILY_API_LIMITS (not duplicated)
  - All paid tiers have Stripe price setting names defined
  - Cost rates align with existing UsageMeteringService constants
"""
from __future__ import annotations

import pytest

from app.billing.constants import BILLABLE_STATUSES, TIER_DAILY_API_LIMITS, SubscriptionStatus
from app.billing.enforcement import BillingEnforcementService
from app.billing.guards import enforce_active_subscription, enforce_usage_limit
from app.financial.quota.quota_limits import PLAN_QUOTAS, PlanTier as QuotaPlanTier
from app.pricing.protection import CostCapExceeded, NegativeMarginThrottle
from app.pricing.tiers import TIER_CATALOG, PlanTier, get_tier
from app.pricing.unit_economics import COST_RATES


# ── Tier naming alignment ─────────────────────────────────────────────────────

def test_pricing_plan_tier_values_are_uppercase():
    """plan_tier DB column stores uppercase; pricing engine must match."""
    for tier in PlanTier:
        assert tier.value == tier.value.upper()


def test_pricing_tier_values_match_tier_daily_api_limits_keys():
    """TIER_DAILY_API_LIMITS uses uppercase string keys — they must overlap."""
    for tier in PlanTier:
        # Each pricing tier must have a corresponding entry in billing constants
        assert tier.value in TIER_DAILY_API_LIMITS, (
            f"{tier.value} missing from TIER_DAILY_API_LIMITS"
        )


def test_daily_api_limits_consistent_between_billing_and_pricing():
    """No silent divergence between billing/constants.py and pricing/tiers.py."""
    for tier in PlanTier:
        billing_limit = TIER_DAILY_API_LIMITS[tier.value]
        pricing_limit = get_tier(tier).daily_api_calls
        assert billing_limit == pricing_limit, (
            f"{tier.value}: billing {billing_limit} != pricing {pricing_limit}"
        )


# ── Monthly char limits alignment ─────────────────────────────────────────────

def test_monthly_chars_align_with_quota_limits():
    """Pricing tiers must match the financial quota limits system."""
    quota_tier_map = {
        PlanTier.FREE:       QuotaPlanTier.FREE,
        PlanTier.BASIC:      QuotaPlanTier.BASIC,
        PlanTier.PRO:        QuotaPlanTier.PRO,
        PlanTier.ENTERPRISE: QuotaPlanTier.ENTERPRISE,
    }
    for pricing_tier, quota_tier in quota_tier_map.items():
        pricing_chars = get_tier(pricing_tier).monthly_chars
        quota_chars   = PLAN_QUOTAS[quota_tier].monthly_char_limit
        assert pricing_chars == quota_chars, (
            f"{pricing_tier.value}: pricing_chars={pricing_chars} != quota_chars={quota_chars}"
        )


def test_monthly_job_limits_align_with_quota_limits():
    quota_tier_map = {
        PlanTier.FREE:       QuotaPlanTier.FREE,
        PlanTier.BASIC:      QuotaPlanTier.BASIC,
        PlanTier.PRO:        QuotaPlanTier.PRO,
        PlanTier.ENTERPRISE: QuotaPlanTier.ENTERPRISE,
    }
    for pricing_tier, quota_tier in quota_tier_map.items():
        pricing_jobs = get_tier(pricing_tier).monthly_jobs
        quota_jobs   = PLAN_QUOTAS[quota_tier].monthly_job_limit
        assert pricing_jobs == quota_jobs, (
            f"{pricing_tier.value}: pricing_jobs={pricing_jobs} != quota_jobs={quota_jobs}"
        )


def test_storage_limits_align_with_quota_limits():
    quota_tier_map = {
        PlanTier.FREE:       QuotaPlanTier.FREE,
        PlanTier.BASIC:      QuotaPlanTier.BASIC,
        PlanTier.PRO:        QuotaPlanTier.PRO,
        PlanTier.ENTERPRISE: QuotaPlanTier.ENTERPRISE,
    }
    for pricing_tier, quota_tier in quota_tier_map.items():
        pricing_storage = get_tier(pricing_tier).storage_mb
        quota_storage   = PLAN_QUOTAS[quota_tier].storage_limit_mb
        assert pricing_storage == quota_storage, (
            f"{pricing_tier.value}: pricing_storage={pricing_storage} != quota_storage={quota_storage}"
        )


# ── Subscription status compatibility ─────────────────────────────────────────

def test_billable_statuses_are_subset_of_subscription_status():
    valid_statuses = {s.value for s in SubscriptionStatus}
    for status in BILLABLE_STATUSES:
        assert status.value in valid_statuses


def test_pricing_guards_use_billable_statuses():
    """enforce_active_subscription must align with BILLABLE_STATUSES."""
    from unittest.mock import MagicMock
    from fastapi import HTTPException

    for status in SubscriptionStatus:
        mock_user = MagicMock()
        mock_user.subscription_status = status.value

        if status in BILLABLE_STATUSES:
            # Should not raise
            enforce_active_subscription(mock_user)
        else:
            with pytest.raises(HTTPException) as exc:
                enforce_active_subscription(mock_user)
            assert exc.value.status_code == 402


# ── Revenue protection exception distinctness ─────────────────────────────────

def test_cost_cap_exceeded_is_not_billing_exception():
    from app.billing.enforcement import QuotaExceeded as BillingQuotaExceeded
    assert not issubclass(CostCapExceeded, BillingQuotaExceeded)


def test_negative_margin_throttle_is_not_billing_exception():
    from app.billing.enforcement import AccountSuspended
    assert not issubclass(NegativeMarginThrottle, AccountSuspended)


# ── guards.enforce_usage_limit alignment ─────────────────────────────────────

def test_enforce_usage_limit_uses_billing_constants():
    """enforce_usage_limit reads from TIER_DAILY_API_LIMITS — not its own table."""
    from unittest.mock import MagicMock
    from fastapi import HTTPException

    mock_user = MagicMock()
    mock_user.plan_tier = "FREE"

    limit = TIER_DAILY_API_LIMITS["FREE"]

    # Below limit — no exception
    enforce_usage_limit(mock_user, current_daily_calls=limit - 1)

    # At limit — exception
    with pytest.raises(HTTPException) as exc:
        enforce_usage_limit(mock_user, current_daily_calls=limit)
    assert exc.value.status_code == 429


# ── Stripe price settings ─────────────────────────────────────────────────────

def test_all_paid_tiers_have_stripe_settings_defined():
    """Every paid tier must reference a settings attribute for its Stripe price ID."""
    from app.core.config import settings

    for tier in (PlanTier.BASIC, PlanTier.PRO, PlanTier.ENTERPRISE):
        cfg = get_tier(tier)
        assert hasattr(settings, cfg.stripe_monthly_price_setting), (
            f"{tier.value} monthly price setting {cfg.stripe_monthly_price_setting!r} "
            "not found in Settings"
        )
        assert hasattr(settings, cfg.stripe_annual_price_setting), (
            f"{tier.value} annual price setting {cfg.stripe_annual_price_setting!r} "
            "not found in Settings"
        )


# ── Cost rate alignment ────────────────────────────────────────────────────────

def test_usage_metering_db_cost_aligns_with_unit_economics():
    """
    The DB query cost in UsageMeteringService must match unit economics rates.
    This prevents the two systems from diverging silently.
    """
    from app.billing.usage_meter import _DB_QUERY_USD, _REDIS_OP_USD

    assert abs(_DB_QUERY_USD - COST_RATES.db_per_query) < 1e-9
    assert abs(_REDIS_OP_USD - COST_RATES.redis_per_op) < 1e-9


# ── No circular imports ────────────────────────────────────────────────────────

def test_pricing_tiers_does_not_import_billing():
    """pricing.tiers must not import from billing.* (one-way dependency)."""
    import importlib
    import sys

    # Ensure pricing.tiers is loaded
    import app.pricing.tiers as tiers_module

    # Check that no billing.* modules were pulled in by pricing.tiers specifically
    # (we do this by checking the module source imports)
    import ast
    import inspect

    source = inspect.getsource(tiers_module)
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            if isinstance(node, ast.ImportFrom) and node.module:
                assert not node.module.startswith("app.billing"), (
                    f"pricing.tiers imports from billing: {node.module}"
                )

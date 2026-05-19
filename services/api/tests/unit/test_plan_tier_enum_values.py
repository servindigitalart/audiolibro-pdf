"""
Unit Tests: plan_tier enum value/name alignment
================================================
Regression guard for the ValueError: 'FREE' is not a valid PlanTier crash.

Root cause: app/financial/quota/quota_limits.py defined PlanTier with lowercase
values ("free") while the database stores uppercase ("FREE") and the canonical
app/pricing/tiers.py enum uses uppercase.  account_service.py and
quota_service.py called PlanTier(user.plan_tier) where user.plan_tier = "FREE"
and crashed because "FREE" was not a valid value in the lowercase enum.

These tests verify:
1. quota_limits.PlanTier values are uppercase (match the DB).
2. quota_limits.PlanTier accepts uppercase input without raising ValueError.
3. quota_limits.PlanTier._missing_ also accepts legacy lowercase input.
4. Both PlanTier enums (pricing.tiers and financial.quota.quota_limits) agree
   on the set of tier names.
5. The pattern used in account_service/quota_service survives real DB values.
"""

import pytest

from app.financial.quota.quota_limits import PlanTier as QuotaPlanTier, PLAN_QUOTAS
from app.pricing.tiers import PlanTier as PricingPlanTier

pytestmark = pytest.mark.unit


# ── Value casing ──────────────────────────────────────────────────────────────

class TestQuotaPlanTierValues:
    def test_free_value_is_uppercase(self):
        assert QuotaPlanTier.FREE.value == "FREE"

    def test_basic_value_is_uppercase(self):
        assert QuotaPlanTier.BASIC.value == "BASIC"

    def test_pro_value_is_uppercase(self):
        assert QuotaPlanTier.PRO.value == "PRO"

    def test_enterprise_value_is_uppercase(self):
        assert QuotaPlanTier.ENTERPRISE.value == "ENTERPRISE"

    def test_all_values_are_uppercase(self):
        for member in QuotaPlanTier:
            assert member.value == member.value.upper(), (
                f"QuotaPlanTier.{member.name}.value must be uppercase; got {member.value!r}"
            )

    def test_member_equals_its_value_string(self):
        """str enum members must compare equal to their .value."""
        assert QuotaPlanTier.FREE == "FREE"
        assert QuotaPlanTier.BASIC == "BASIC"
        assert QuotaPlanTier.PRO == "PRO"
        assert QuotaPlanTier.ENTERPRISE == "ENTERPRISE"


# ── Lookup from DB values (the crash scenario) ────────────────────────────────

class TestQuotaPlanTierLookupFromDB:
    """
    Simulates what account_service._get_remaining_quota() and
    quota_service.check_quota() do: PlanTier(user.plan_tier) where
    user.plan_tier is the raw string from the database column.
    """

    def test_construct_from_uppercase_free(self):
        """'FREE' must not raise — this was the crash site."""
        tier = QuotaPlanTier("FREE")
        assert tier is QuotaPlanTier.FREE

    def test_construct_from_uppercase_basic(self):
        tier = QuotaPlanTier("BASIC")
        assert tier is QuotaPlanTier.BASIC

    def test_construct_from_uppercase_pro(self):
        tier = QuotaPlanTier("PRO")
        assert tier is QuotaPlanTier.PRO

    def test_construct_from_uppercase_enterprise(self):
        tier = QuotaPlanTier("ENTERPRISE")
        assert tier is QuotaPlanTier.ENTERPRISE

    def test_plan_quotas_keyed_by_all_tiers(self):
        """PLAN_QUOTAS must have an entry for every tier (quota lookup must not KeyError)."""
        for tier in QuotaPlanTier:
            assert tier in PLAN_QUOTAS, f"PLAN_QUOTAS missing key for {tier!r}"

    def test_construct_then_index_plan_quotas(self):
        """Full simulation of the crashing code path — must not raise."""
        for raw_db_value in ("FREE", "BASIC", "PRO", "ENTERPRISE"):
            tier = QuotaPlanTier(raw_db_value)
            limits = PLAN_QUOTAS[tier]
            assert limits is not None


# ── _missing_ hook: legacy lowercase tolerance ────────────────────────────────

class TestQuotaPlanTierMissing:
    """
    _missing_ must accept lowercase values so any stale rows survive without
    crashing, even before migration 013 has run.
    """

    def test_lowercase_free_resolves_via_missing(self):
        tier = QuotaPlanTier("free")
        assert tier is QuotaPlanTier.FREE

    def test_lowercase_basic_resolves_via_missing(self):
        tier = QuotaPlanTier("basic")
        assert tier is QuotaPlanTier.BASIC

    def test_lowercase_pro_resolves_via_missing(self):
        tier = QuotaPlanTier("pro")
        assert tier is QuotaPlanTier.PRO

    def test_lowercase_enterprise_resolves_via_missing(self):
        tier = QuotaPlanTier("enterprise")
        assert tier is QuotaPlanTier.ENTERPRISE

    def test_mixed_case_resolves_via_missing(self):
        assert QuotaPlanTier("Free") is QuotaPlanTier.FREE
        assert QuotaPlanTier("pRo") is QuotaPlanTier.PRO

    def test_invalid_value_returns_none_via_missing(self):
        result = QuotaPlanTier._missing_("INVALID")
        assert result is None

    def test_invalid_value_raises_value_error(self):
        with pytest.raises(ValueError):
            QuotaPlanTier("INVALID_TIER")


# ── Cross-enum consistency ────────────────────────────────────────────────────

class TestPlanTierEnumConsistency:
    """
    pricing/tiers.py PlanTier and financial/quota/quota_limits.py PlanTier
    must agree on the set of tier names and values.
    """

    def test_same_member_names(self):
        quota_names = {m.name for m in QuotaPlanTier}
        pricing_names = {m.name for m in PricingPlanTier}
        assert quota_names == pricing_names, (
            f"Tier name mismatch between enums: "
            f"quota={quota_names}, pricing={pricing_names}"
        )

    def test_same_values(self):
        quota_values = {m.value for m in QuotaPlanTier}
        pricing_values = {m.value for m in PricingPlanTier}
        assert quota_values == pricing_values, (
            f"Tier value mismatch between enums: "
            f"quota={quota_values}, pricing={pricing_values}"
        )

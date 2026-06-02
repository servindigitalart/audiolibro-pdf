"""
Unit Tests: Plan Calibration (Phase 3.6)
=========================================
Tests for:
  - TierConfig.approx_listening_hours_min/max fields on all tiers
  - Listening-hour values are internally consistent with monthly_chars
  - UnitEconomicsEngine full_report() margin health
  - Per-tier profitability checks at expected utilization rates
  - Listening-hour / cost tradeoff sanity checks
"""
import pytest

from app.pricing.tiers import TIER_CATALOG, PlanTier, get_tier
from app.pricing.unit_economics import UnitEconomicsEngine, CHARS_PER_LISTENING_HOUR

pytestmark = pytest.mark.unit


# ── TierConfig.approx_listening_hours fields ──────────────────────────────────

@pytest.mark.parametrize("tier", list(PlanTier))
def test_tier_has_listening_hour_fields(tier):
    config = get_tier(tier)
    assert hasattr(config, "approx_listening_hours_min")
    assert hasattr(config, "approx_listening_hours_max")


@pytest.mark.parametrize("tier", list(PlanTier))
def test_listening_hours_min_lte_max(tier):
    config = get_tier(tier)
    assert config.approx_listening_hours_min <= config.approx_listening_hours_max


@pytest.mark.parametrize("tier", list(PlanTier))
def test_listening_hours_are_positive(tier):
    config = get_tier(tier)
    assert config.approx_listening_hours_min > 0
    assert config.approx_listening_hours_max > 0


@pytest.mark.parametrize("tier", list(PlanTier))
def test_listening_hours_max_does_not_exceed_theoretical(tier):
    config = get_tier(tier)
    theoretical_max = config.monthly_chars / CHARS_PER_LISTENING_HOUR
    # approx_listening_hours_max should be conservative (≤ theoretical)
    assert config.approx_listening_hours_max <= theoretical_max + 0.01, (
        f"{tier}: approx_listening_hours_max ({config.approx_listening_hours_max}) "
        f"exceeds theoretical ({theoretical_max:.1f})"
    )


def test_tier_ordering_listening_hours():
    """Higher tiers must advertise more listening hours than lower tiers."""
    free  = get_tier(PlanTier.FREE)
    basic = get_tier(PlanTier.BASIC)
    pro   = get_tier(PlanTier.PRO)
    ent   = get_tier(PlanTier.ENTERPRISE)

    assert free.approx_listening_hours_max  < basic.approx_listening_hours_min
    assert basic.approx_listening_hours_max < pro.approx_listening_hours_min
    assert pro.approx_listening_hours_max   < ent.approx_listening_hours_min


# ── Specific listening-hour expectations ─────────────────────────────────────

def test_free_tier_listening_hours_range():
    config = get_tier(PlanTier.FREE)
    assert config.approx_listening_hours_min >= 0.1
    assert config.approx_listening_hours_max <= 1.5


def test_basic_tier_listening_hours_range():
    config = get_tier(PlanTier.BASIC)
    assert config.approx_listening_hours_min >= 1.0
    assert config.approx_listening_hours_max <= 5.0


def test_pro_tier_listening_hours_range():
    config = get_tier(PlanTier.PRO)
    assert config.approx_listening_hours_min >= 5.0
    assert config.approx_listening_hours_max <= 20.0


def test_enterprise_tier_listening_hours_range():
    config = get_tier(PlanTier.ENTERPRISE)
    assert config.approx_listening_hours_min >= 20.0
    assert config.approx_listening_hours_max <= 200.0


# ── UnitEconomicsEngine profitability ────────────────────────────────────────

@pytest.fixture
def engine():
    return UnitEconomicsEngine()


def test_paid_tiers_profitable_at_60pct_utilization(engine):
    for tier in (PlanTier.BASIC, PlanTier.PRO, PlanTier.ENTERPRISE):
        te = engine.tier_economics(tier, utilization_rate=0.60)
        assert te.is_profitable, (
            f"{tier} not profitable at 60% utilization "
            f"(margin: {te.gross_margin_pct:.1f}%)"
        )


def test_free_tier_is_unprofitable(engine):
    te = engine.tier_economics(PlanTier.FREE, utilization_rate=0.60)
    assert not te.is_profitable, "FREE tier should always be unprofitable"


def test_pro_margin_above_40pct_at_60pct_utilization(engine):
    te = engine.tier_economics(PlanTier.PRO, utilization_rate=0.60)
    assert te.gross_margin_pct >= 40.0, (
        f"PRO margin at 60% util is too thin: {te.gross_margin_pct:.1f}%"
    )


def test_basic_margin_above_0pct_at_60pct_utilization(engine):
    te = engine.tier_economics(PlanTier.BASIC, utilization_rate=0.60)
    assert te.gross_margin_pct > 0.0, (
        f"BASIC margin at 60% util is negative: {te.gross_margin_pct:.1f}%"
    )


def test_full_report_overall_healthy_with_paid_tiers(engine):
    report = engine.full_report()
    assert report.overall_healthy, (
        f"full_report not healthy. warnings: {report.warnings}"
    )


def test_full_report_contains_all_tiers(engine):
    report = engine.full_report()
    tier_names = {te.tier for te in report.tiers}
    assert tier_names == set(PlanTier)


def test_break_even_utilization_is_between_0_and_1(engine):
    for tier in PlanTier:
        te = engine.tier_economics(tier)
        assert 0.0 <= te.break_even_utilization <= 1.0, (
            f"{tier}: break_even_utilization out of range: {te.break_even_utilization}"
        )


# ── Cost caps are consistent with monthly prices ──────────────────────────────

@pytest.mark.parametrize("tier", [PlanTier.BASIC, PlanTier.PRO, PlanTier.ENTERPRISE])
def test_max_monthly_cost_below_monthly_price(tier):
    config = get_tier(tier)
    assert config.max_monthly_cost_usd < config.monthly_price_usd, (
        f"{tier}: max_monthly_cost_usd ({config.max_monthly_cost_usd}) "
        f">= monthly_price_usd ({config.monthly_price_usd}) — no margin floor"
    )


@pytest.mark.parametrize("tier", list(PlanTier))
def test_max_daily_cost_is_positive(tier):
    config = get_tier(tier)
    assert config.max_daily_cost_usd > 0


# ── Margin label sanity ───────────────────────────────────────────────────────

def test_pro_at_60pct_has_healthy_or_acceptable_margin(engine):
    te = engine.tier_economics(PlanTier.PRO, 0.60)
    assert te.margin_label in ("healthy", "acceptable"), (
        f"PRO margin_label at 60%: {te.margin_label} ({te.gross_margin_pct:.1f}%)"
    )


def test_free_tier_has_negative_margin_label(engine):
    te = engine.tier_economics(PlanTier.FREE, 0.60)
    assert te.margin_label == "negative"

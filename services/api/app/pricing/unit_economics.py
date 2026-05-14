"""
Unit Economics Engine
======================
Calculates per-user and per-tier profitability from first-principles cost rates.

Cost drivers (primary source: Google Cloud TTS + DO Spaces + compute):
  TTS Neural2/WaveNet : $0.000016 per character  ($16/1M)
  TTS Standard voices : $0.000004 per character  ($4/1M)
  Storage             : $0.000023 per MB/month   ($23/TB/month)
  Bandwidth           : $0.00001  per MB download
  Stripe fee          : 2.9% + $0.30 per charge
  DB query overhead   : $0.000001 per query
  Redis operation     : $0.00000005 per op
  Compute             : $0.00000003 per ms wall-clock

Design:
  - All rates in UnitCostRates dataclass so tests can inject different rates
  - COST_RATES is the production singleton
  - UnitEconomicsEngine is stateless — feed it usage numbers, get margins back
  - ProfitabilityReport is the output type for the admin health endpoint
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional

from app.pricing.tiers import TIER_CATALOG, PlanTier, TierConfig


# ── Cost rate definitions ─────────────────────────────────────────────────────

@dataclass(frozen=True)
class UnitCostRates:
    """All per-unit costs in USD.  Override in tests or for pricing experiments."""

    # TTS
    tts_neural_per_char: float   = 0.000016    # $16 per 1M chars (Neural2 / WaveNet)
    tts_standard_per_char: float = 0.000004    # $4  per 1M chars (Standard)

    # Storage (DO Spaces / S3-compatible)
    storage_per_mb_month: float  = 0.000023    # $23 per TB/month

    # Bandwidth
    bandwidth_per_mb: float      = 0.00001     # $10 per TB download

    # Infrastructure
    db_per_query: float          = 0.000001    # $1 per 1M queries
    redis_per_op: float          = 0.00000005  # $0.05 per 1M ops
    compute_per_ms: float        = 0.00000003  # $0.03 per 1M ms wall-clock

    # Stripe transaction costs
    stripe_rate: float           = 0.029       # 2.9% of transaction
    stripe_flat: float           = 0.30        # $0.30 per successful charge

    # Overhead amortisation (infra, support, ops) per active user/month
    infra_overhead_per_user: float = 0.15      # conservative estimate


COST_RATES = UnitCostRates()


# ── Per-request cost calculation ──────────────────────────────────────────────

@dataclass
class RequestCost:
    """Detailed cost breakdown for a single request."""
    tts_chars: int = 0
    storage_mb_delta: float = 0.0
    bandwidth_mb: float = 0.0
    db_queries: int = 0
    redis_ops: int = 0
    compute_ms: float = 0.0
    use_neural_tts: bool = True            # PRO+ use neural; FREE/BASIC use standard

    def total_usd(self, rates: UnitCostRates = COST_RATES) -> float:
        tts_rate = rates.tts_neural_per_char if self.use_neural_tts else rates.tts_standard_per_char
        return (
            self.tts_chars          * tts_rate
            + self.storage_mb_delta * rates.storage_per_mb_month
            + self.bandwidth_mb     * rates.bandwidth_per_mb
            + self.db_queries       * rates.db_per_query
            + self.redis_ops        * rates.redis_per_op
            + self.compute_ms       * rates.compute_per_ms
        )


# ── Per-tier economics ────────────────────────────────────────────────────────

@dataclass
class TierEconomics:
    """
    Unit economics model for one pricing tier at a given utilization level.

    utilization_rate: 0.0 – 1.0 fraction of monthly limits consumed.
    """
    tier: PlanTier
    utilization_rate: float          # 0.0 = no usage, 1.0 = full quota

    # Computed fields (populated by UnitEconomicsEngine)
    monthly_revenue_gross: float = 0.0
    stripe_fee: float = 0.0
    monthly_revenue_net: float = 0.0

    tts_cost: float = 0.0
    storage_cost: float = 0.0
    infra_overhead: float = 0.0
    total_cost: float = 0.0

    gross_profit: float = 0.0
    gross_margin_pct: float = 0.0     # 0–100
    is_profitable: bool = True

    break_even_utilization: float = 0.0  # fraction at which profit = 0

    @property
    def margin_label(self) -> str:
        if self.gross_margin_pct >= 70:
            return "healthy"
        if self.gross_margin_pct >= 40:
            return "acceptable"
        if self.gross_margin_pct >= 0:
            return "thin"
        return "negative"


@dataclass
class ProfitabilityReport:
    """
    Summary profitability report across all tiers.
    Returned by the /internal/pricing/economics admin endpoint.
    """
    tiers: list[TierEconomics]
    overall_healthy: bool
    warnings: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "tiers": [
                {
                    "tier": te.tier.value,
                    "utilization_rate": te.utilization_rate,
                    "monthly_revenue_net_usd": round(te.monthly_revenue_net, 4),
                    "total_cost_usd": round(te.total_cost, 4),
                    "gross_profit_usd": round(te.gross_profit, 4),
                    "gross_margin_pct": round(te.gross_margin_pct, 1),
                    "margin_label": te.margin_label,
                    "is_profitable": te.is_profitable,
                    "break_even_utilization": round(te.break_even_utilization, 4),
                }
                for te in self.tiers
            ],
            "overall_healthy": self.overall_healthy,
            "warnings": self.warnings,
        }


# ── Engine ────────────────────────────────────────────────────────────────────

class UnitEconomicsEngine:
    """
    Stateless calculator for tier-level and per-user profitability.

    Inject a custom UnitCostRates to model pricing experiments or cost changes.
    """

    def __init__(self, rates: UnitCostRates = COST_RATES) -> None:
        self._rates = rates

    # ── Tier-level analysis ───────────────────────────────────────────────────

    def tier_economics(
        self,
        tier: PlanTier,
        utilization_rate: float = 0.60,
    ) -> TierEconomics:
        """
        Calculate economics for `tier` at the given utilization rate.

        utilization_rate: expected fraction of quota consumed (0.6 = typical active user).
        """
        config = TIER_CATALOG[tier]
        r = self._rates

        # Revenue
        gross_rev = config.monthly_price_usd
        stripe_fee = gross_rev * r.stripe_rate + (r.stripe_flat if gross_rev > 0 else 0.0)
        net_rev = gross_rev - stripe_fee

        # TTS cost — PRO and ENTERPRISE get neural voices; FREE and BASIC get standard
        use_neural = tier in (PlanTier.PRO, PlanTier.ENTERPRISE)
        tts_rate = r.tts_neural_per_char if use_neural else r.tts_standard_per_char
        chars_used = config.monthly_chars * utilization_rate
        tts_cost = chars_used * tts_rate

        # Storage cost — assume 50% of max storage used on average
        storage_cost = (config.storage_mb * 0.5) * r.storage_per_mb_month

        # Infra overhead
        infra = r.infra_overhead_per_user

        total_cost = tts_cost + storage_cost + infra
        gross_profit = net_rev - total_cost
        margin_pct = (gross_profit / net_rev * 100) if net_rev > 0 else -math.inf

        # Break-even: find utilization where profit = 0
        # net_rev - (chars_at_breakeven × tts_rate) - storage_cost - infra = 0
        # chars_at_breakeven = (net_rev - storage_cost - infra) / tts_rate
        if tts_rate > 0 and config.monthly_chars > 0:
            breakeven_chars = (net_rev - storage_cost - infra) / tts_rate
            breakeven_util = max(0.0, breakeven_chars / config.monthly_chars)
        else:
            breakeven_util = 0.0 if net_rev > 0 else 1.0

        return TierEconomics(
            tier=tier,
            utilization_rate=utilization_rate,
            monthly_revenue_gross=gross_rev,
            stripe_fee=stripe_fee,
            monthly_revenue_net=net_rev,
            tts_cost=tts_cost,
            storage_cost=storage_cost,
            infra_overhead=infra,
            total_cost=total_cost,
            gross_profit=gross_profit,
            gross_margin_pct=max(-999.0, margin_pct),
            is_profitable=gross_profit >= 0,
            break_even_utilization=min(1.0, breakeven_util),
        )

    def full_report(
        self,
        utilization_rates: Optional[dict[PlanTier, float]] = None,
    ) -> ProfitabilityReport:
        """
        Generate profitability report across all tiers.

        utilization_rates: override per-tier utilization (defaults to 60%).
        """
        defaults = {t: 0.60 for t in PlanTier}
        rates = {**defaults, **(utilization_rates or {})}

        tiers = [self.tier_economics(t, rates[t]) for t in PlanTier]
        warnings: list[str] = []

        for te in tiers:
            if not te.is_profitable:
                warnings.append(
                    f"{te.tier.value} is unprofitable at {te.utilization_rate:.0%} utilization "
                    f"(margin: {te.gross_margin_pct:.1f}%)"
                )
            elif te.gross_margin_pct < 30:
                warnings.append(
                    f"{te.tier.value} has thin margin ({te.gross_margin_pct:.1f}%) "
                    f"at {te.utilization_rate:.0%} utilization"
                )

        # overall_healthy only considers PAID tiers — free tier running at a loss is expected
        paid_tiers = [te for te in tiers if te.monthly_revenue_gross > 0]
        return ProfitabilityReport(
            tiers=tiers,
            overall_healthy=all(te.is_profitable for te in paid_tiers),
            warnings=warnings,
        )

    # ── Per-user analysis ─────────────────────────────────────────────────────

    def user_cost(
        self,
        tier: PlanTier,
        *,
        chars_used: int,
        storage_mb: float,
        api_calls: int = 0,
        bandwidth_mb: float = 0.0,
    ) -> float:
        """
        Calculate the actual cost of serving a specific user this month.

        Use this to detect negative-margin users in real time.
        """
        config = TIER_CATALOG[tier]
        r = self._rates

        use_neural = tier in (PlanTier.PRO, PlanTier.ENTERPRISE)
        tts_rate = r.tts_neural_per_char if use_neural else r.tts_standard_per_char

        # Approximate API call compute cost: assume 50ms average latency
        compute_ms = api_calls * 50.0

        return (
            chars_used    * tts_rate
            + storage_mb  * r.storage_per_mb_month
            + bandwidth_mb* r.bandwidth_per_mb
            + compute_ms  * r.compute_per_ms
            + r.infra_overhead_per_user
        )

    def is_negative_margin_user(
        self,
        tier: PlanTier,
        monthly_cost: float,
    ) -> bool:
        """
        Return True if this user is generating more cost than revenue.

        For FREE users this is always True for active users (by design).
        For paid users this signals an abuse or runaway case.
        """
        config = TIER_CATALOG[tier]
        net_rev = config.monthly_price_usd
        if net_rev > 0:
            net_rev -= net_rev * self._rates.stripe_rate + self._rates.stripe_flat
        return monthly_cost > net_rev

    def profit_per_user(
        self,
        tier: PlanTier,
        monthly_cost: float,
    ) -> float:
        """Return (net_revenue - monthly_cost) for a specific user."""
        config = TIER_CATALOG[tier]
        net_rev = config.monthly_price_usd
        if net_rev > 0:
            net_rev -= net_rev * self._rates.stripe_rate + self._rates.stripe_flat
        return net_rev - monthly_cost

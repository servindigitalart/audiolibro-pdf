"""
Pricing Test Fixtures
======================
Shared fixtures for the pricing test suite.
All pricing tests are pure-unit — no DB or Redis required unless noted.
"""
from __future__ import annotations

import pytest

from app.pricing.experiments import ExperimentService, LimitOverride, PricingExperiment
from app.pricing.tiers import PlanTier
from app.pricing.unit_economics import UnitCostRates, UnitEconomicsEngine
from app.pricing.upgrade import UpgradeEvaluator, UsageSnapshot


@pytest.fixture
def evaluator() -> UpgradeEvaluator:
    return UpgradeEvaluator()


@pytest.fixture
def engine() -> UnitEconomicsEngine:
    return UnitEconomicsEngine()


@pytest.fixture
def cheap_rates() -> UnitCostRates:
    """Cost rates 10× cheaper — for testing profitability at low cost."""
    return UnitCostRates(
        tts_neural_per_char=0.0000016,
        tts_standard_per_char=0.0000004,
        infra_overhead_per_user=0.015,
    )


@pytest.fixture
def expensive_rates() -> UnitCostRates:
    """Cost rates 3× more expensive — for testing margin squeeze."""
    return UnitCostRates(
        tts_neural_per_char=0.000048,
        tts_standard_per_char=0.000012,
        infra_overhead_per_user=0.45,
    )


@pytest.fixture
def experiment_registry():
    """A clean experiment registry with a single treatment for testing."""
    return {
        "test_exp": PricingExperiment(
            experiment_id="test_exp",
            description="Test experiment",
            eligible_tiers=frozenset({PlanTier.FREE}),
            rollout_pct=100,     # everyone in treatment
            active=True,
            treatment_overrides=LimitOverride(monthly_chars=20_000),
        ),
    }


@pytest.fixture
def exp_service(experiment_registry) -> ExperimentService:
    return ExperimentService(registry=experiment_registry)


@pytest.fixture
def free_snapshot() -> UsageSnapshot:
    return UsageSnapshot(
        user_id="user-free-001",
        tier=PlanTier.FREE,
        chars_used=0,
        jobs_created=0,
        storage_mb=0,
        daily_api_calls=0,
        daily_cost_usd=0.0,
    )

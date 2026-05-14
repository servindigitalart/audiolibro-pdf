"""
Pricing Engine — HTTP Router
==============================
Endpoints:
  GET  /api/v1/pricing/tiers                  — public tier catalog
  GET  /api/v1/pricing/tiers/{tier}           — single tier detail
  GET  /api/v1/pricing/limits/{user_id}       — effective limits for user (with experiments)
  GET  /internal/pricing/economics            — unit economics report (admin)
  GET  /internal/pricing/profitability        — full profitability model at custom utilization (admin)
  POST /internal/pricing/experiments/activate — enable/disable experiment (admin)
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.billing.constants import SubscriptionStatus
from app.core.auth_dependencies import require_admin
from app.db.session import get_db
from app.pricing.experiments import ACTIVE_EXPERIMENTS, ExperimentService
from app.pricing.tiers import TIER_CATALOG, PlanTier, TierFeature, get_tier, stripe_price_id
from app.pricing.unit_economics import UnitEconomicsEngine

public_router  = APIRouter(prefix="/api/v1/pricing", tags=["pricing"])
internal_router = APIRouter(prefix="/internal/pricing", tags=["internal-pricing"])


# ── Helpers ───────────────────────────────────────────────────────────────────

def _serialize_tier(tier_enum: PlanTier, *, include_price_ids: bool = False) -> dict:
    cfg = get_tier(tier_enum)
    d = {
        "tier": cfg.tier.value,
        "monthly_price_usd": cfg.monthly_price_usd,
        "annual_price_usd": cfg.annual_price_usd,
        "annual_savings_usd": round(cfg.monthly_price_usd * 12 - cfg.annual_price_usd, 2),
        "limits": {
            "monthly_chars": cfg.monthly_chars,
            "monthly_jobs": cfg.monthly_jobs,
            "concurrent_jobs": cfg.concurrent_jobs,
            "storage_mb": cfg.storage_mb,
            "daily_api_calls": cfg.daily_api_calls,
            "api_calls_per_minute": cfg.api_calls_per_minute,
        },
        "features": sorted(f.value for f in cfg.features),
        "max_team_members": cfg.max_team_members,
        "trial_days": cfg.trial_days,
        "upgrades_to": cfg.upgrades_to.value if cfg.upgrades_to else None,
    }
    if include_price_ids:
        d["stripe_price_ids"] = {
            "monthly": stripe_price_id(tier_enum, annual=False),
            "annual": stripe_price_id(tier_enum, annual=True),
        }
    return d


# ── Public endpoints ──────────────────────────────────────────────────────────

@public_router.get("/tiers")
async def list_tiers():
    """Public pricing tier catalog."""
    return {
        "tiers": [_serialize_tier(t) for t in PlanTier],
    }


@public_router.get("/tiers/{tier_name}")
async def get_tier_detail(tier_name: str):
    """Public detail for a single tier."""
    try:
        tier = PlanTier(tier_name.upper())
    except ValueError:
        raise HTTPException(status_code=404, detail=f"Unknown tier {tier_name!r}")
    return _serialize_tier(tier, include_price_ids=True)


@public_router.get("/limits/{user_id}")
async def get_effective_limits(
    user_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
):
    """
    Return the effective limits for a user, taking into account any active
    pricing experiments they are enrolled in.
    """
    from sqlalchemy import select
    from app.db.models.user import User

    result = await session.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")

    try:
        tier = PlanTier(user.plan_tier.upper())
    except (ValueError, AttributeError):
        tier = PlanTier.FREE

    svc = ExperimentService()
    effective = svc.get_effective_limits(str(user_id), tier)
    base = get_tier(tier)

    changes = {}
    if effective.monthly_chars != base.monthly_chars:
        changes["monthly_chars"] = {"base": base.monthly_chars, "effective": effective.monthly_chars}
    if effective.monthly_jobs != base.monthly_jobs:
        changes["monthly_jobs"] = {"base": base.monthly_jobs, "effective": effective.monthly_jobs}
    if effective.trial_days != base.trial_days:
        changes["trial_days"] = {"base": base.trial_days, "effective": effective.trial_days}

    return {
        "user_id": str(user_id),
        "tier": tier.value,
        "limits": {
            "monthly_chars": effective.monthly_chars,
            "monthly_jobs": effective.monthly_jobs,
            "storage_mb": effective.storage_mb,
            "daily_api_calls": effective.daily_api_calls,
        },
        "experiment_active": bool(changes),
        "experiment_changes": changes,
    }


# ── Internal admin endpoints ──────────────────────────────────────────────────

@internal_router.get("/economics")
async def unit_economics(
    utilization: float = Query(default=0.60, ge=0.0, le=1.0),
    _admin=Depends(require_admin),
):
    """Unit economics at the given utilization rate across all tiers."""
    engine = UnitEconomicsEngine()
    report = engine.full_report(
        utilization_rates={t: utilization for t in PlanTier}
    )
    return report.as_dict()


@internal_router.get("/profitability")
async def profitability_model(
    free_utilization: float   = Query(default=0.30, ge=0.0, le=1.0),
    basic_utilization: float  = Query(default=0.55, ge=0.0, le=1.0),
    pro_utilization: float    = Query(default=0.65, ge=0.0, le=1.0),
    enterprise_utilization: float = Query(default=0.50, ge=0.0, le=1.0),
    _admin=Depends(require_admin),
):
    """Full profitability model with per-tier utilization inputs."""
    engine = UnitEconomicsEngine()
    report = engine.full_report(
        utilization_rates={
            PlanTier.FREE:       free_utilization,
            PlanTier.BASIC:      basic_utilization,
            PlanTier.PRO:        pro_utilization,
            PlanTier.ENTERPRISE: enterprise_utilization,
        }
    )
    return report.as_dict()


@internal_router.post("/experiments/activate")
async def toggle_experiment(
    experiment_id: str,
    active: bool,
    _admin=Depends(require_admin),
):
    """Enable or disable a pricing experiment without code deployment."""
    if experiment_id not in ACTIVE_EXPERIMENTS:
        raise HTTPException(status_code=404, detail=f"Experiment {experiment_id!r} not found")
    # Mutate the module-level registry (in-process — restarts required for full rollback)
    ACTIVE_EXPERIMENTS[experiment_id].active = active  # type: ignore[misc]
    return {
        "experiment_id": experiment_id,
        "active": active,
        "message": f"Experiment {'activated' if active else 'deactivated'}. "
                   "Deploy or restart to guarantee all instances are updated.",
    }


@internal_router.get("/experiments")
async def list_experiments(_admin=Depends(require_admin)):
    """List all registered pricing experiments and their status."""
    return {
        "experiments": [
            {
                "experiment_id": exp.experiment_id,
                "description": exp.description,
                "eligible_tiers": [t.value for t in exp.eligible_tiers],
                "rollout_pct": exp.rollout_pct,
                "active": exp.active,
            }
            for exp in ACTIVE_EXPERIMENTS.values()
        ]
    }

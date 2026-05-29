"""
Affiliate Router — Public & User-Facing
=========================================
Public endpoints (no auth):
  POST /api/v1/referral/track        — log a click
  GET  /api/v1/referral/validate/{slug} — check if code is active

Authenticated endpoints:
  GET /api/v1/affiliate/me           — my affiliate profile (if I am an affiliate)
  GET /api/v1/affiliate/dashboard    — my stats
"""
from __future__ import annotations

import hashlib
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.affiliate.affiliate_service import AffiliateService
from app.core.auth_dependencies import get_current_active_user
from app.db.models.user import User
from app.db.session import get_async_db as get_db

logger = logging.getLogger(__name__)

# Two routers — mounted at different prefixes
referral_router  = APIRouter(prefix="/api/v1/referral",  tags=["affiliate"])
affiliate_router = APIRouter(prefix="/api/v1/affiliate", tags=["affiliate"])


# ── Public: click tracking ────────────────────────────────────────────────────

class TrackClickRequest(BaseModel):
    slug:         str
    visitor_id:   Optional[str] = None
    landing_path: Optional[str] = None


@referral_router.post("/track", status_code=202)
async def track_referral_click(
    body:    TrackClickRequest,
    request: Request,
    db:      AsyncSession = Depends(get_db),
):
    """
    Record an affiliate link visit.  Always returns 202 so errors never
    surface to the visitor.

    Privacy: hashes user-agent + IP before storing — no raw PII.
    """
    try:
        aff = await AffiliateService.get_by_slug(db, body.slug)
        if not aff or aff.status != "active":
            return {"tracked": False, "reason": "inactive"}

        raw_ua = request.headers.get("user-agent", "")
        raw_ip = (request.client.host if request.client else "") or ""

        await AffiliateService.track_click(
            db,
            affiliate_id=aff.id,
            visitor_id=body.visitor_id,
            landing_path=body.landing_path,
            raw_user_agent=raw_ua or None,
            raw_ip=raw_ip or None,
        )
        return {"tracked": True}
    except Exception as exc:
        logger.warning("referral_track_error slug=%s error=%s", body.slug, exc)
        return {"tracked": False}


# ── Public: validate code ─────────────────────────────────────────────────────

@referral_router.get("/validate/{slug}")
async def validate_referral_code(
    slug: str,
    db:   AsyncSession = Depends(get_db),
):
    """
    Check whether a referral code is valid and active.
    Returns affiliate name so the frontend can show "Referred by <name>".
    """
    aff = await AffiliateService.get_by_slug(db, slug)
    if not aff or aff.status != "active":
        raise HTTPException(status_code=404, detail="Referral code not found or inactive")
    return {
        "valid":  True,
        "slug":   aff.slug,
        "name":   aff.name,
        "status": aff.status,
    }


# ── Authenticated: affiliate self-service ─────────────────────────────────────

@affiliate_router.get("/me")
async def get_my_affiliate_profile(
    current_user: User   = Depends(get_current_active_user),
    db: AsyncSession     = Depends(get_db),
):
    """
    Return the affiliate profile associated with the current user account.
    404 if this user is not an affiliate.
    """
    from sqlalchemy import select
    from app.db.models.affiliate import Affiliate

    result = await db.execute(
        select(Affiliate).where(Affiliate.user_id == current_user.id)
    )
    aff = result.scalar_one_or_none()
    if not aff:
        raise HTTPException(status_code=404, detail="You are not registered as an affiliate")

    return {
        "id":                  str(aff.id),
        "name":                aff.name,
        "email":               aff.email,
        "slug":                aff.slug,
        "status":              aff.status,
        "commission_rate_pct": aff.commission_rate_pct,
        "referral_link":       f"/?ref={aff.slug}",
        "created_at":          aff.created_at.isoformat() if aff.created_at else None,
    }


@affiliate_router.get("/dashboard")
async def get_my_affiliate_dashboard(
    current_user: User   = Depends(get_current_active_user),
    db: AsyncSession     = Depends(get_db),
):
    """
    Return clicks, signups, conversions, and commission totals for the
    current user's affiliate account.
    """
    from sqlalchemy import select
    from app.db.models.affiliate import Affiliate, AffiliateConversion

    result = await db.execute(
        select(Affiliate).where(Affiliate.user_id == current_user.id)
    )
    aff = result.scalar_one_or_none()
    if not aff:
        raise HTTPException(status_code=404, detail="You are not registered as an affiliate")

    stats = await AffiliateService.get_stats(db, aff.id)

    # Recent conversions (last 20)
    convs = await AffiliateService.list_conversions(db, affiliate_id=aff.id, limit=20)

    return {
        "affiliate": {
            "slug":                aff.slug,
            "name":                aff.name,
            "status":              aff.status,
            "commission_rate_pct": aff.commission_rate_pct,
            "referral_link":       f"/?ref={aff.slug}",
        },
        "stats": stats,
        "recent_conversions": [
            {
                "plan_tier":             c.plan_tier,
                "amount_usd":            c.amount_usd,
                "commission_amount_usd": c.commission_amount_usd,
                "status":                c.status,
                "created_at":            c.created_at.isoformat() if c.created_at else None,
            }
            for c in convs
        ],
    }

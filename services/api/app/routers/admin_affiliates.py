"""
Admin Affiliates Router
=======================
CRUD + performance management for the affiliate program.
All endpoints are admin-only.
"""
from __future__ import annotations

import logging
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, EmailStr
from sqlalchemy.ext.asyncio import AsyncSession

from app.affiliate.affiliate_service import AffiliateService
from app.core.auth_dependencies import require_admin
from app.db.models.user import User
from app.db.session import get_async_db as get_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/admin/affiliates", tags=["admin", "affiliates"])


# ── Request schemas ───────────────────────────────────────────────────────────

class CreateAffiliateRequest(BaseModel):
    name:                str
    email:               EmailStr
    slug:                Optional[str] = None
    commission_rate_pct: float = 20.0


class UpdateAffiliateRequest(BaseModel):
    status:              Optional[str]  = None   # pending/active/paused
    commission_rate_pct: Optional[float] = None
    name:                Optional[str]  = None
    email:               Optional[EmailStr] = None


# ── Helpers ───────────────────────────────────────────────────────────────────

def _aff_dict(aff) -> dict:
    return {
        "id":                  str(aff.id),
        "user_id":             str(aff.user_id) if aff.user_id else None,
        "name":                aff.name,
        "email":               aff.email,
        "slug":                aff.slug,
        "status":              aff.status,
        "commission_rate_pct": aff.commission_rate_pct,
        "created_at":          aff.created_at.isoformat() if aff.created_at else None,
        "updated_at":          aff.updated_at.isoformat() if aff.updated_at else None,
    }


def _conv_dict(conv) -> dict:
    return {
        "id":                    str(conv.id),
        "affiliate_id":          str(conv.affiliate_id),
        "referred_user_id":      str(conv.referred_user_id) if conv.referred_user_id else None,
        "stripe_event_id":       conv.stripe_event_id,
        "stripe_customer_id":    conv.stripe_customer_id,
        "stripe_subscription_id": conv.stripe_subscription_id,
        "plan_tier":             conv.plan_tier,
        "amount_usd":            conv.amount_usd,
        "commission_pct":        conv.commission_pct,
        "commission_amount_usd": conv.commission_amount_usd,
        "status":                conv.status,
        "created_at":            conv.created_at.isoformat() if conv.created_at else None,
        "updated_at":            conv.updated_at.isoformat() if conv.updated_at else None,
    }


# ── Affiliate CRUD ────────────────────────────────────────────────────────────

@router.get("/summary")
async def get_affiliate_summary(
    current_user: User = Depends(require_admin),
    db: AsyncSession   = Depends(get_db),
):
    """Top affiliates + aggregate totals — for the admin dashboard card."""
    data = await AffiliateService.get_summary(db)
    logger.info("admin_affiliate_summary_accessed admin_id=%s", current_user.id)
    return data


@router.get("")
async def list_affiliates(
    status: Optional[str] = Query(default=None),
    limit:  int           = Query(default=50, ge=1, le=200),
    offset: int           = Query(default=0,  ge=0),
    current_user: User    = Depends(require_admin),
    db: AsyncSession      = Depends(get_db),
):
    """List affiliates with optional status filter."""
    affiliates = await AffiliateService.list_affiliates(db, status=status, limit=limit, offset=offset)
    result = []
    for aff in affiliates:
        stats = await AffiliateService.get_stats(db, aff.id)
        result.append({**_aff_dict(aff), "stats": stats})
    return {"affiliates": result, "count": len(result)}


@router.post("", status_code=201)
async def create_affiliate(
    body: CreateAffiliateRequest,
    current_user: User = Depends(require_admin),
    db: AsyncSession   = Depends(get_db),
):
    """Create a new affiliate account."""
    try:
        aff = await AffiliateService.create_affiliate(
            db,
            name=body.name,
            email=body.email,
            slug=body.slug,
            commission_rate_pct=body.commission_rate_pct,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    logger.info("admin_affiliate_created slug=%s by=%s", aff.slug, current_user.id)
    return _aff_dict(aff)


@router.get("/{affiliate_id}")
async def get_affiliate(
    affiliate_id: UUID,
    current_user: User = Depends(require_admin),
    db: AsyncSession   = Depends(get_db),
):
    """Get affiliate details + performance stats."""
    aff = await AffiliateService.get_by_id(db, affiliate_id)
    if not aff:
        raise HTTPException(status_code=404, detail="Affiliate not found")
    stats = await AffiliateService.get_stats(db, aff.id)
    return {**_aff_dict(aff), "stats": stats}


@router.patch("/{affiliate_id}")
async def update_affiliate(
    affiliate_id: UUID,
    body: UpdateAffiliateRequest,
    current_user: User = Depends(require_admin),
    db: AsyncSession   = Depends(get_db),
):
    """Update affiliate status, commission rate, or contact info."""
    aff = await AffiliateService.update_affiliate(
        db, affiliate_id,
        status=body.status,
        commission_rate_pct=body.commission_rate_pct,
        name=body.name,
        email=str(body.email) if body.email else None,
    )
    if not aff:
        raise HTTPException(status_code=404, detail="Affiliate not found")
    logger.info("admin_affiliate_updated id=%s by=%s", affiliate_id, current_user.id)
    return _aff_dict(aff)


# ── Conversions ───────────────────────────────────────────────────────────────

@router.get("/{affiliate_id}/conversions")
async def list_affiliate_conversions(
    affiliate_id: UUID,
    status:  Optional[str] = Query(default=None),
    limit:   int           = Query(default=50, ge=1, le=200),
    offset:  int           = Query(default=0,  ge=0),
    current_user: User     = Depends(require_admin),
    db: AsyncSession       = Depends(get_db),
):
    """List conversions for one affiliate."""
    convs = await AffiliateService.list_conversions(db, affiliate_id=affiliate_id, status=status, limit=limit, offset=offset)
    return {"conversions": [_conv_dict(c) for c in convs], "count": len(convs)}


@router.get("/{affiliate_id}/clicks")
async def list_affiliate_clicks(
    affiliate_id: UUID,
    limit:   int       = Query(default=50, ge=1, le=200),
    current_user: User = Depends(require_admin),
    db: AsyncSession   = Depends(get_db),
):
    """List recent click events for one affiliate."""
    from sqlalchemy import select as sa_select
    from app.db.models.affiliate import AffiliateClick

    rows = (await db.execute(
        sa_select(AffiliateClick)
        .where(AffiliateClick.affiliate_id == affiliate_id)
        .order_by(AffiliateClick.created_at.desc())
        .limit(limit)
    )).scalars().all()

    return {
        "clicks": [
            {
                "id":                  str(c.id),
                "visitor_id":          c.visitor_id,
                "landing_path":        c.landing_path,
                "converted_to_signup": c.converted_to_signup,
                "created_at":          c.created_at.isoformat() if c.created_at else None,
            }
            for c in rows
        ],
        "count": len(rows),
    }


# ── Conversion payout management ──────────────────────────────────────────────

_conv_router = APIRouter(prefix="/api/v1/admin/conversions", tags=["admin", "affiliates"])


@_conv_router.get("")
async def list_all_conversions(
    status:  Optional[str] = Query(default=None),
    limit:   int           = Query(default=50, ge=1, le=200),
    offset:  int           = Query(default=0,  ge=0),
    current_user: User     = Depends(require_admin),
    db: AsyncSession       = Depends(get_db),
):
    """List all conversions across affiliates."""
    convs = await AffiliateService.list_conversions(db, status=status, limit=limit, offset=offset)
    return {"conversions": [_conv_dict(c) for c in convs], "count": len(convs)}


@_conv_router.post("/{conversion_id}/approve")
async def approve_conversion(
    conversion_id: UUID,
    current_user: User = Depends(require_admin),
    db: AsyncSession   = Depends(get_db),
):
    """Approve a pending conversion (sets status → approved)."""
    conv = await AffiliateService.approve_conversion(db, conversion_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversion not found")
    return _conv_dict(conv)


@_conv_router.post("/{conversion_id}/paid")
async def mark_paid(
    conversion_id: UUID,
    current_user: User = Depends(require_admin),
    db: AsyncSession   = Depends(get_db),
):
    """Mark an approved conversion as paid (manual payout recorded)."""
    conv = await AffiliateService.mark_payout_paid(db, conversion_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversion not found")
    return _conv_dict(conv)


@_conv_router.post("/{conversion_id}/reverse")
async def reverse_conversion(
    conversion_id: UUID,
    current_user: User = Depends(require_admin),
    db: AsyncSession   = Depends(get_db),
):
    """Reverse a conversion (refund/chargeback scenario)."""
    conv = await AffiliateService.reverse_conversion(db, conversion_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversion not found")
    return _conv_dict(conv)

"""
Affiliate Service
=================
All business logic for the referral program.

Design:
  - All write methods are idempotent or defend against duplicates
  - Errors in affiliate attribution never propagate to the caller
  - Commission is calculated at conversion time and locked into the row
  - Payouts are manual: pending → approved → paid workflow
"""
from __future__ import annotations

import hashlib
import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.affiliate import Affiliate, AffiliateClick, AffiliateConversion

logger = logging.getLogger(__name__)

_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9\-]{1,48}[a-z0-9]$")

VALID_STATUSES   = {"pending", "active", "paused"}
VALID_CONV_STATS = {"pending", "approved", "paid", "reversed"}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _slugify(name: str) -> str:
    """Convert a name to a URL-safe slug (lowercase, hyphens)."""
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower().strip())
    slug = slug.strip("-")
    return slug[:50] if len(slug) >= 3 else slug + "-ref"


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()[:64]


# ── Service ───────────────────────────────────────────────────────────────────

class AffiliateService:

    # ── Read ──────────────────────────────────────────────────────────────────

    @staticmethod
    async def get_by_slug(db: AsyncSession, slug: str) -> Affiliate | None:
        """Return Affiliate by slug, or None if not found."""
        result = await db.execute(
            select(Affiliate).where(Affiliate.slug == slug.lower())
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def get_by_id(db: AsyncSession, affiliate_id: UUID) -> Affiliate | None:
        result = await db.execute(
            select(Affiliate).where(Affiliate.id == affiliate_id)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def is_active_slug(db: AsyncSession, slug: str) -> bool:
        """Return True only if the slug exists and status == 'active'."""
        aff = await AffiliateService.get_by_slug(db, slug)
        return aff is not None and aff.status == "active"

    @staticmethod
    async def list_affiliates(
        db: AsyncSession, status: str | None = None, limit: int = 100, offset: int = 0
    ) -> list[Affiliate]:
        q = select(Affiliate)
        if status:
            q = q.where(Affiliate.status == status)
        q = q.order_by(Affiliate.created_at.desc()).limit(limit).offset(offset)
        return list((await db.execute(q)).scalars().all())

    @staticmethod
    async def get_stats(db: AsyncSession, affiliate_id: UUID) -> dict[str, Any]:
        """Aggregate stats for one affiliate: clicks, signups, conversions, commission."""
        clicks_total = await db.scalar(
            select(func.count(AffiliateClick.id))
            .where(AffiliateClick.affiliate_id == affiliate_id)
        ) or 0

        signups = await db.scalar(
            select(func.count(AffiliateClick.id))
            .where(AffiliateClick.affiliate_id == affiliate_id)
            .where(AffiliateClick.converted_to_signup.is_(True))
        ) or 0

        conv_rows = (await db.execute(
            select(
                AffiliateConversion.status,
                func.count(AffiliateConversion.id),
                func.sum(AffiliateConversion.commission_amount_usd),
            )
            .where(AffiliateConversion.affiliate_id == affiliate_id)
            .group_by(AffiliateConversion.status)
        )).all()

        conv_by_status: dict[str, dict[str, Any]] = {}
        for row in conv_rows:
            conv_by_status[row[0]] = {"count": row[1], "commission_usd": round(float(row[2] or 0), 2)}

        total_commission = sum(v["commission_usd"] for v in conv_by_status.values())
        pending_commission = (conv_by_status.get("pending", {}).get("commission_usd", 0) +
                              conv_by_status.get("approved", {}).get("commission_usd", 0))
        paid_commission = conv_by_status.get("paid", {}).get("commission_usd", 0)
        total_conversions = sum(v["count"] for v in conv_by_status.values()
                                if v and conv_by_status.get(list(conv_by_status.keys())[list(conv_by_status.values()).index(v)], {}).get("count", 0))

        # recount cleanly
        total_paid_convs = conv_by_status.get("paid", {}).get("count", 0)
        total_all_convs  = sum(v["count"] for v in conv_by_status.values())

        return {
            "clicks": clicks_total,
            "signups": signups,
            "conversions_total": total_all_convs,
            "conversions_paid": total_paid_convs,
            "commission_pending_usd": round(pending_commission, 2),
            "commission_paid_usd":    round(paid_commission, 2),
            "commission_total_usd":   round(total_commission, 2),
            "by_status": conv_by_status,
        }

    @staticmethod
    async def get_summary(db: AsyncSession, limit: int = 5) -> dict[str, Any]:
        """Top affiliates + aggregate totals — for the admin dashboard card."""
        from app.db.models.affiliate import AffiliateConversion as AC

        total_clicks = await db.scalar(select(func.count(AffiliateClick.id))) or 0
        total_signups = await db.scalar(
            select(func.count(AffiliateClick.id))
            .where(AffiliateClick.converted_to_signup.is_(True))
        ) or 0
        total_conversions = await db.scalar(select(func.count(AC.id))) or 0
        pending_commission = float(await db.scalar(
            select(func.sum(AC.commission_amount_usd))
            .where(AC.status.in_(["pending", "approved"]))
        ) or 0)
        paid_commission = float(await db.scalar(
            select(func.sum(AC.commission_amount_usd)).where(AC.status == "paid")
        ) or 0)

        top_aff = (await db.execute(
            select(Affiliate)
            .order_by(Affiliate.created_at.desc())
            .limit(limit)
        )).scalars().all()

        top_list = []
        for aff in top_aff:
            stats = await AffiliateService.get_stats(db, aff.id)
            top_list.append({
                "id":     str(aff.id),
                "name":   aff.name,
                "slug":   aff.slug,
                "status": aff.status,
                **stats,
            })

        return {
            "totals": {
                "clicks":              total_clicks,
                "signups":             total_signups,
                "conversions":         total_conversions,
                "pending_commission":  round(pending_commission, 2),
                "paid_commission":     round(paid_commission, 2),
            },
            "top_affiliates": top_list,
        }

    # ── Write ─────────────────────────────────────────────────────────────────

    @staticmethod
    async def create_affiliate(
        db: AsyncSession,
        name: str,
        email: str,
        slug: str | None = None,
        commission_rate_pct: float = 20.0,
        user_id: UUID | None = None,
    ) -> Affiliate:
        """Create a new affiliate. Slug is auto-generated from name if not provided."""
        if not slug:
            base = _slugify(name)
            slug = base
            # Ensure uniqueness by appending random suffix if needed
            existing = await AffiliateService.get_by_slug(db, slug)
            if existing:
                slug = f"{base}-{str(uuid.uuid4())[:6]}"

        slug = slug.lower()
        if not _SLUG_RE.match(slug):
            raise ValueError(f"Invalid slug {slug!r}: must be 3–50 lowercase alphanumeric/hyphen chars")

        affiliate = Affiliate(
            user_id=user_id,
            name=name,
            email=email,
            slug=slug,
            status="pending",
            commission_rate_pct=commission_rate_pct,
        )
        db.add(affiliate)
        await db.commit()
        await db.refresh(affiliate)
        logger.info("[SONORO] affiliate_created slug=%s id=%s", slug, affiliate.id)
        return affiliate

    @staticmethod
    async def update_affiliate(
        db: AsyncSession,
        affiliate_id: UUID,
        *,
        status: str | None = None,
        commission_rate_pct: float | None = None,
        name: str | None = None,
        email: str | None = None,
    ) -> Affiliate | None:
        aff = await AffiliateService.get_by_id(db, affiliate_id)
        if not aff:
            return None
        if status and status in VALID_STATUSES:
            aff.status = status
        if commission_rate_pct is not None and 0 < commission_rate_pct <= 100:
            aff.commission_rate_pct = commission_rate_pct
        if name:
            aff.name = name
        if email:
            aff.email = email
        aff.updated_at = datetime.now(timezone.utc)
        await db.commit()
        await db.refresh(aff)
        return aff

    @staticmethod
    async def track_click(
        db: AsyncSession,
        affiliate_id: UUID,
        visitor_id: str | None = None,
        landing_path: str | None = None,
        raw_user_agent: str | None = None,
        raw_ip: str | None = None,
    ) -> AffiliateClick:
        """Record a link visit. Hashes UA and IP before storing."""
        click = AffiliateClick(
            affiliate_id=affiliate_id,
            visitor_id=visitor_id,
            landing_path=landing_path[:500] if landing_path else None,
            user_agent_hash=_hash(raw_user_agent) if raw_user_agent else None,
            ip_hash=_hash(raw_ip) if raw_ip else None,
        )
        db.add(click)
        try:
            await db.commit()
            await db.refresh(click)
            logger.info("[SONORO] affiliate_click_tracked affiliate_id=%s visitor=%s", affiliate_id, visitor_id)
        except Exception:
            await db.rollback()
        return click

    @staticmethod
    async def attribute_signup(
        db: AsyncSession,
        user_id: UUID,
        slug: str,
        visitor_id: str | None = None,
    ) -> bool:
        """
        Link a newly-created user to an affiliate on signup.

        Returns True if attribution succeeded, False otherwise.
        Fails silently so registration is never blocked.
        """
        try:
            aff = await AffiliateService.get_by_slug(db, slug)
            if not aff or aff.status != "active":
                return False

            from app.db.models.user import User
            await db.execute(
                update(User)
                .where(User.id == user_id)
                .where(User.referred_by_affiliate_id.is_(None))  # no overwrite
                .values(referred_by_affiliate_id=aff.id)
            )

            # Mark any matching click row as converted
            if visitor_id:
                await db.execute(
                    update(AffiliateClick)
                    .where(AffiliateClick.affiliate_id == aff.id)
                    .where(AffiliateClick.visitor_id == visitor_id)
                    .where(AffiliateClick.converted_to_signup.is_(False))
                    .values(converted_to_signup=True, user_id=user_id)
                )

            await db.commit()
            logger.info(
                "[SONORO] affiliate_signup_attributed user_id=%s affiliate_slug=%s affiliate_id=%s",
                user_id, slug, aff.id,
            )
            return True
        except Exception as exc:
            logger.warning("affiliate_attribution_failed slug=%s user_id=%s error=%s", slug, user_id, exc)
            await db.rollback()
            return False

    @staticmethod
    async def record_conversion(
        db: AsyncSession,
        *,
        user_id: UUID,
        stripe_event_id: str,
        stripe_customer_id: str | None,
        stripe_subscription_id: str | None,
        plan_tier: str,
        amount_usd: float,
    ) -> AffiliateConversion | None:
        """
        Create an affiliate conversion for a confirmed Stripe payment.

        Idempotent: if stripe_event_id already exists, returns None without error.
        Only creates a conversion if user has referred_by_affiliate_id set.
        """
        try:
            from app.db.models.user import User

            user_row = await db.execute(
                select(User.referred_by_affiliate_id).where(User.id == user_id)
            )
            user_scalar = user_row.scalar_one_or_none()
            if not user_scalar:
                return None  # user has no affiliate attribution

            aff = await AffiliateService.get_by_id(db, user_scalar)
            if not aff:
                return None

            commission_pct = aff.commission_rate_pct
            commission_usd = round(amount_usd * commission_pct / 100, 4)

            conversion = AffiliateConversion(
                affiliate_id=aff.id,
                referred_user_id=user_id,
                stripe_customer_id=stripe_customer_id,
                stripe_subscription_id=stripe_subscription_id,
                stripe_event_id=stripe_event_id,
                plan_tier=plan_tier,
                amount_usd=amount_usd,
                commission_pct=commission_pct,
                commission_amount_usd=commission_usd,
                status="pending",
            )
            db.add(conversion)
            await db.commit()
            await db.refresh(conversion)

            logger.info(
                "[SONORO] affiliate_conversion_created affiliate_id=%s user_id=%s "
                "plan=%s amount=%.2f commission=%.4f event=%s",
                aff.id, user_id, plan_tier, amount_usd, commission_usd, stripe_event_id,
            )
            logger.info(
                "[SONORO] affiliate_commission_pending affiliate_id=%s commission_usd=%.4f status=pending",
                aff.id, commission_usd,
            )
            return conversion

        except IntegrityError:
            await db.rollback()
            logger.info("affiliate_conversion_duplicate_event event_id=%s", stripe_event_id)
            return None
        except Exception as exc:
            await db.rollback()
            logger.error("affiliate_conversion_failed user_id=%s event=%s error=%s", user_id, stripe_event_id, exc)
            return None

    @staticmethod
    async def _transition_conversion(
        db: AsyncSession, conversion_id: UUID, new_status: str
    ) -> AffiliateConversion | None:
        result = await db.execute(
            select(AffiliateConversion).where(AffiliateConversion.id == conversion_id)
        )
        conv = result.scalar_one_or_none()
        if not conv:
            return None
        conv.status = new_status
        conv.updated_at = datetime.now(timezone.utc)
        await db.commit()
        await db.refresh(conv)
        return conv

    @staticmethod
    async def approve_conversion(db: AsyncSession, conversion_id: UUID) -> AffiliateConversion | None:
        conv = await AffiliateService._transition_conversion(db, conversion_id, "approved")
        if conv:
            logger.info("affiliate_conversion_approved id=%s commission=%.4f", conversion_id, conv.commission_amount_usd)
        return conv

    @staticmethod
    async def mark_payout_paid(db: AsyncSession, conversion_id: UUID) -> AffiliateConversion | None:
        conv = await AffiliateService._transition_conversion(db, conversion_id, "paid")
        if conv:
            logger.info(
                "[SONORO] affiliate_payout_marked_paid id=%s affiliate_id=%s commission=%.4f",
                conversion_id, conv.affiliate_id, conv.commission_amount_usd,
            )
        return conv

    @staticmethod
    async def reverse_conversion(db: AsyncSession, conversion_id: UUID) -> AffiliateConversion | None:
        conv = await AffiliateService._transition_conversion(db, conversion_id, "reversed")
        if conv:
            logger.info("affiliate_conversion_reversed id=%s", conversion_id)
        return conv

    @staticmethod
    async def list_conversions(
        db: AsyncSession,
        affiliate_id: UUID | None = None,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[AffiliateConversion]:
        q = select(AffiliateConversion)
        if affiliate_id:
            q = q.where(AffiliateConversion.affiliate_id == affiliate_id)
        if status:
            q = q.where(AffiliateConversion.status == status)
        q = q.order_by(AffiliateConversion.created_at.desc()).limit(limit).offset(offset)
        return list((await db.execute(q)).scalars().all())

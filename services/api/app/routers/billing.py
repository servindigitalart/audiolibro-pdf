"""
Billing Router
==============
Stripe billing and subscription management endpoints.

Uses:
  - app.billing.stripe.factory.get_stripe_provider() for all Stripe API calls
  - app.billing.webhook.WebhookService for signature validation, idempotency, and
    state-machine dispatch
  - app.pricing.tiers.stripe_price_id() to resolve tier → Stripe price ID

The legacy app.services.stripe_service module is no longer used here.
"""

import uuid
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Header, status
from fastapi.responses import JSONResponse
from sqlalchemy import update as sa_update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import get_logger, settings
from app.db import get_db
from app.db.models import User
from app.core.auth_dependencies import get_current_user
from app.billing.stripe.factory import get_stripe_provider
from app.billing.stripe.base import StripeProvider, StripeError
from app.billing.webhook import WebhookService, InvalidSignature
from app.pricing.tiers import stripe_price_id, PlanTier
from app.schemas.billing import (
    CheckoutRequest,
    CheckoutResponse,
    SubscriptionResponse,
    PortalRequest,
    PortalResponse,
    CancelSubscriptionRequest,
)

logger = get_logger(__name__)

router = APIRouter(prefix="/billing", tags=["billing"])


def _get_provider() -> StripeProvider:
    """Per-request Stripe provider (mock or real, driven by STRIPE_MODE)."""
    return get_stripe_provider()


def _billing_url(path: str) -> str:
    """Build an absolute URL relative to the configured frontend."""
    base = (settings.frontend_url or "http://localhost:3000").rstrip("/")
    return f"{base}{path}"


def _resolve_price_id(request: CheckoutRequest) -> str:
    """
    Resolve the Stripe price ID from the request.

    Priority:
      1. Explicit price_id (API / direct callers)
      2. tier + interval (frontend path)
    """
    if request.price_id:
        return request.price_id

    if not request.tier:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Either price_id or tier must be provided.",
        )

    try:
        plan = PlanTier(request.tier.upper())
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown tier {request.tier!r}. Valid values: BASIC, PRO, ENTERPRISE.",
        )

    annual = request.interval.lower() in ("annual", "yearly", "year")
    price = stripe_price_id(plan, annual=annual)
    if not price:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"No Stripe price configured for tier={plan.value} interval={request.interval}. "
                   "Check STRIPE_PRICE_* environment variables.",
        )
    return price


# ── Checkout ──────────────────────────────────────────────────────────────────

@router.post("/checkout", response_model=CheckoutResponse)
async def create_checkout_session(
    request: CheckoutRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    provider: Annotated[StripeProvider, Depends(_get_provider)],
) -> CheckoutResponse:
    """
    Create a Stripe checkout session for subscription.

    Flow:
      1. Resolve Stripe price ID from tier+interval (or explicit price_id)
      2. Create/retrieve Stripe customer and save customer_id to DB
      3. Create checkout session with metadata (user_id + tier)
      4. Return checkout URL — frontend redirects user there
    """
    price = _resolve_price_id(request)
    tier = request.tier or ""
    success_url = request.success_url or _billing_url("/dashboard/billing?checkout=success")
    cancel_url  = request.cancel_url  or _billing_url("/dashboard/billing?checkout=cancelled")

    try:
        # 1. Create Stripe customer if this user doesn't have one yet
        customer_id: Optional[str] = current_user.stripe_customer_id
        if not customer_id:
            customer = await provider.create_customer(
                email=current_user.email,
                user_id=str(current_user.id),
            )
            customer_id = customer.id
            await db.execute(
                sa_update(User)
                .where(User.id == current_user.id)
                .values(stripe_customer_id=customer_id)
            )
            await db.commit()
            logger.info(
                "[SONORO] stripe_customer_created user_id=%s customer_id=%s",
                current_user.id, customer_id,
            )

        # 2. Create the hosted checkout session
        idempotency_key = f"checkout-{current_user.id}-{price}"
        session = await provider.create_checkout_session(
            customer_id=customer_id,
            price_id=price,
            success_url=success_url,
            cancel_url=cancel_url,
            idempotency_key=idempotency_key,
            trial_days=request.trial_days or 0,
            metadata={"user_id": str(current_user.id), "tier": tier},
        )

        logger.info(
            "[SONORO] stripe_checkout_created user_id=%s tier=%s price_id=%s session_id=%s",
            current_user.id, tier, price, session.id,
        )

        return CheckoutResponse(session_id=session.id, url=session.url)

    except StripeError as exc:
        logger.error(
            "[SONORO] stripe_checkout_failed user_id=%s tier=%s error=%s",
            current_user.id, tier, exc,
        )
        raise HTTPException(status_code=502, detail=f"Stripe error: {exc}")
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("[SONORO] stripe_checkout_unexpected user_id=%s error=%s", current_user.id, exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to create checkout session")


# ── Webhook ───────────────────────────────────────────────────────────────────

@router.post("/webhook")
async def handle_stripe_webhook(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    stripe_signature: Annotated[Optional[str], Header(alias="stripe-signature")] = None,
) -> JSONResponse:
    """
    Handle Stripe webhook events.

    Security: validates HMAC-SHA256 signature (Stripe-Signature header).
    Idempotency: deduplicates by stripe_event_id — safe to replay.
    State machine: delegates to WebhookService which drives SubscriptionService.
    """
    payload = await request.body()

    webhook_svc = WebhookService(
        session=db,
        webhook_secret=settings.stripe_webhook_secret or "",
    )

    try:
        event = await webhook_svc.process(payload, stripe_signature or "")
    except InvalidSignature as exc:
        logger.error("[SONORO] stripe_webhook_invalid_signature error=%s", exc)
        raise HTTPException(status_code=400, detail="Invalid webhook signature")
    except Exception as exc:
        logger.error("[SONORO] stripe_webhook_processing_failed error=%s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Webhook processing failed")

    return JSONResponse(
        status_code=200,
        content={"status": "ok", "event_id": event.stripe_event_id},
    )


# ── Subscription read ─────────────────────────────────────────────────────────

@router.get("/subscription", response_model=SubscriptionResponse)
async def get_subscription(
    current_user: Annotated[User, Depends(get_current_user)],
    provider: Annotated[StripeProvider, Depends(_get_provider)],
) -> SubscriptionResponse:
    """Return current subscription details, augmented with live Stripe data."""
    cancel_at_period_end: Optional[bool] = None

    if current_user.stripe_subscription_id:
        try:
            sub = await provider.get_subscription(current_user.stripe_subscription_id)
            if sub:
                cancel_at_period_end = sub.cancel_at_period_end
        except StripeError as exc:
            logger.warning(
                "[SONORO] stripe_subscription_fetch_failed sub_id=%s error=%s",
                current_user.stripe_subscription_id, exc,
            )

    return SubscriptionResponse(
        subscription_id=current_user.stripe_subscription_id,
        customer_id=current_user.stripe_customer_id,
        status=current_user.subscription_status,
        plan_tier=current_user.plan_tier,
        current_period_end=current_user.current_period_end,
        cancel_at_period_end=cancel_at_period_end,
    )


# ── Customer portal ───────────────────────────────────────────────────────────

@router.post("/portal", response_model=PortalResponse)
async def create_portal_session(
    request: PortalRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    provider: Annotated[StripeProvider, Depends(_get_provider)],
) -> PortalResponse:
    """Create a Stripe Customer Portal session for self-serve billing management."""
    if not current_user.stripe_customer_id:
        raise HTTPException(
            status_code=400,
            detail="No Stripe customer linked to this account. Subscribe first.",
        )

    try:
        return_url = request.return_url or _billing_url("/dashboard/billing")
        url = await provider.create_billing_portal_session(
            customer_id=current_user.stripe_customer_id,
            return_url=return_url,
        )
        logger.info(
            "[SONORO] stripe_portal_created user_id=%s customer_id=%s",
            current_user.id, current_user.stripe_customer_id,
        )
        return PortalResponse(url=url)
    except StripeError as exc:
        logger.error("[SONORO] stripe_portal_failed user_id=%s error=%s", current_user.id, exc)
        raise HTTPException(status_code=502, detail=f"Stripe error: {exc}")


# ── Cancel subscription ───────────────────────────────────────────────────────

@router.delete("/subscription")
async def cancel_subscription(
    request: CancelSubscriptionRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    provider: Annotated[StripeProvider, Depends(_get_provider)],
) -> JSONResponse:
    """
    Cancel the user's subscription.

    immediately=False (default): cancels at period end — user retains access.
    immediately=True: cancels now, no proration refund.
    """
    if not current_user.stripe_subscription_id:
        raise HTTPException(status_code=400, detail="No active subscription found.")

    try:
        sub = await provider.cancel_subscription(
            subscription_id=current_user.stripe_subscription_id,
            immediately=request.immediately,
        )

        if request.immediately:
            await db.execute(
                sa_update(User)
                .where(User.id == current_user.id)
                .values(
                    subscription_status="canceled",
                    stripe_subscription_id=None,
                    plan_tier="FREE",
                )
            )
            await db.commit()

        logger.info(
            "[SONORO] stripe_subscription_cancelled user_id=%s sub_id=%s immediately=%s",
            current_user.id, current_user.stripe_subscription_id, request.immediately,
        )

        return JSONResponse(
            status_code=200,
            content={
                "status": "success",
                "message": (
                    "Subscription cancelled immediately"
                    if request.immediately
                    else "Subscription will cancel at period end"
                ),
                "cancel_at_period_end": sub.cancel_at_period_end,
            },
        )
    except StripeError as exc:
        logger.error("[SONORO] stripe_cancel_failed user_id=%s error=%s", current_user.id, exc)
        raise HTTPException(status_code=502, detail=f"Stripe error: {exc}")

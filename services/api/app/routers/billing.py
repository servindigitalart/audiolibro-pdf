"""
Billing Router
==============
Stripe billing and subscription management endpoints.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Header
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import get_logger, settings
from app.db import get_db
from app.db.models import User
from app.core.auth_dependencies import get_current_user
from app.schemas.billing import (
    CheckoutRequest,
    CheckoutResponse,
    SubscriptionResponse,
    PortalRequest,
    PortalResponse,
    CancelSubscriptionRequest,
)
from app.services.stripe_service import StripeService

logger = get_logger(__name__)

router = APIRouter(prefix="/billing", tags=["billing"])


def get_stripe_service() -> StripeService:
    """Dependency to get StripeService instance."""
    return StripeService()


@router.post("/checkout", response_model=CheckoutResponse)
async def create_checkout_session(
    request: CheckoutRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    stripe_service: Annotated[StripeService, Depends(get_stripe_service)],
) -> CheckoutResponse:
    """
    Create a Stripe checkout session for subscription.
    
    **Flow:**
    1. User selects a plan on frontend
    2. Frontend calls this endpoint with price_id
    3. Returns checkout URL
    4. User completes payment on Stripe
    5. Webhook updates user subscription
    """
    try:
        logger.info(
            f"Creating checkout session for user {current_user.id}, price_id={request.price_id}"
        )
        
        # Create checkout session
        session = await stripe_service.create_checkout_session(
            user_id=str(current_user.id),
            user_email=current_user.email,
            price_id=request.price_id,
            success_url=request.success_url,
            cancel_url=request.cancel_url,
            promotion_code=request.promotion_code,
            trial_days=request.trial_days,
        )
        
        logger.info(
            f"Checkout session created: {session.id} for user {current_user.id}"
        )
        
        return CheckoutResponse(
            session_id=session.id,
            url=session.url,
        )
    except Exception as e:
        logger.error(f"Failed to create checkout session: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to create checkout session: {str(e)}"
        )


@router.post("/webhook")
async def handle_stripe_webhook(
    request: Request,
    stripe_signature: Annotated[str, Header(alias="stripe-signature")],
    db: Annotated[AsyncSession, Depends(get_db)],
    stripe_service: Annotated[StripeService, Depends(get_stripe_service)],
) -> JSONResponse:
    """
    Handle Stripe webhook events.
    
    **Security:**
    - Validates webhook signature
    - Rejects unsigned requests
    
    **Events handled:**
    - checkout.session.completed
    - customer.subscription.created
    - customer.subscription.updated
    - customer.subscription.deleted
    - invoice.payment_succeeded
    - invoice.payment_failed
    """
    try:
        # Get raw body for signature verification
        payload = await request.body()
        
        # Verify webhook signature
        event = await stripe_service.verify_webhook_signature(
            payload=payload,
            signature=stripe_signature,
        )
        
        logger.info(f"Received webhook event: {event.type} (id={event.id})")
        
        # Handle the event
        result = await stripe_service.handle_webhook_event(event, db)
        
        logger.info(
            f"Webhook event {event.type} processed successfully: {result}"
        )
        
        return JSONResponse(
            status_code=200,
            content={"status": "success", "event_id": event.id}
        )
    except ValueError as e:
        logger.error(f"Invalid webhook signature: {e}")
        raise HTTPException(status_code=400, detail="Invalid signature")
    except Exception as e:
        logger.error(f"Webhook processing failed: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Webhook processing failed: {str(e)}"
        )


@router.get("/subscription", response_model=SubscriptionResponse)
async def get_subscription(
    current_user: Annotated[User, Depends(get_current_user)],
    stripe_service: Annotated[StripeService, Depends(get_stripe_service)],
) -> SubscriptionResponse:
    """
    Get current user's subscription details.
    
    **Returns:**
    - Subscription status
    - Plan tier
    - Billing period end
    - Cancel status
    """
    try:
        # Get subscription details from Stripe if subscription exists
        cancel_at_period_end = None
        
        if current_user.stripe_subscription_id:
            try:
                subscription = await stripe_service.retrieve_subscription(
                    current_user.stripe_subscription_id
                )
                cancel_at_period_end = subscription.cancel_at_period_end
            except Exception as e:
                logger.warning(
                    f"Failed to fetch subscription from Stripe: {e}. "
                    "Using database values."
                )
        
        return SubscriptionResponse(
            subscription_id=current_user.stripe_subscription_id,
            customer_id=current_user.stripe_customer_id,
            status=current_user.subscription_status,
            plan_tier=current_user.plan_tier,
            current_period_end=current_user.current_period_end,
            cancel_at_period_end=cancel_at_period_end,
        )
    except Exception as e:
        logger.error(f"Failed to get subscription: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get subscription: {str(e)}"
        )


@router.post("/portal", response_model=PortalResponse)
async def create_portal_session(
    request: PortalRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    stripe_service: Annotated[StripeService, Depends(get_stripe_service)],
) -> PortalResponse:
    """
    Create a Stripe Customer Portal session.
    
    **Portal allows users to:**
    - Update payment method
    - View invoices
    - Cancel subscription
    - Update billing information
    """
    try:
        if not current_user.stripe_customer_id:
            raise HTTPException(
                status_code=400,
                detail="No Stripe customer ID found. Please subscribe first."
            )
        
        logger.info(
            f"Creating portal session for user {current_user.id}, "
            f"customer_id={current_user.stripe_customer_id}"
        )
        
        # Create portal session
        session = await stripe_service.create_portal_session(
            customer_id=current_user.stripe_customer_id,
            return_url=request.return_url,
        )
        
        logger.info(
            f"Portal session created for user {current_user.id}: {session.id}"
        )
        
        return PortalResponse(url=session.url)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to create portal session: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to create portal session: {str(e)}"
        )


@router.delete("/subscription")
async def cancel_subscription(
    request: CancelSubscriptionRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    stripe_service: Annotated[StripeService, Depends(get_stripe_service)],
) -> JSONResponse:
    """
    Cancel user's subscription.
    
    **Options:**
    - immediately=False: Cancel at period end (default)
    - immediately=True: Cancel immediately with no refund
    """
    try:
        if not current_user.stripe_subscription_id:
            raise HTTPException(
                status_code=400,
                detail="No active subscription found"
            )
        
        logger.info(
            f"Cancelling subscription for user {current_user.id}, "
            f"immediately={request.immediately}"
        )
        
        # Cancel subscription
        subscription = await stripe_service.cancel_subscription(
            subscription_id=current_user.stripe_subscription_id,
            immediately=request.immediately,
        )
        
        # Update database
        if request.immediately:
            current_user.subscription_status = "canceled"
            current_user.stripe_subscription_id = None
            current_user.plan_tier = "FREE"
        else:
            current_user.subscription_status = "active"  # Still active until period end
        
        await db.commit()
        
        logger.info(
            f"Subscription cancelled for user {current_user.id}: {subscription.id}"
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
                "cancel_at_period_end": subscription.cancel_at_period_end,
            }
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to cancel subscription: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to cancel subscription: {str(e)}"
        )

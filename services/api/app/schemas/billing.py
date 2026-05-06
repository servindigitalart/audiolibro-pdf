"""
Billing Schemas
===============
Pydantic schemas for Stripe billing operations.
"""

from datetime import datetime
from typing import Optional, Dict, Any
from pydantic import BaseModel, Field, ConfigDict


class CheckoutRequest(BaseModel):
    """Request to create a checkout session."""
    
    price_id: str = Field(
        ..., 
        description="Stripe price ID for the subscription"
    )
    success_url: str = Field(
        ...,
        description="URL to redirect to after successful payment"
    )
    cancel_url: str = Field(
        ...,
        description="URL to redirect to if payment is cancelled"
    )
    promotion_code: Optional[str] = Field(
        None,
        description="Optional promotion code to apply"
    )
    trial_days: Optional[int] = Field(
        None,
        ge=0,
        le=365,
        description="Number of trial days (0-365)"
    )


class CheckoutResponse(BaseModel):
    """Response containing checkout session details."""
    
    session_id: str = Field(..., description="Stripe checkout session ID")
    url: str = Field(..., description="Checkout URL to redirect user to")
    
    model_config = ConfigDict(from_attributes=True)


class SubscriptionResponse(BaseModel):
    """Response containing subscription details."""
    
    subscription_id: Optional[str] = Field(None, description="Stripe subscription ID")
    customer_id: Optional[str] = Field(None, description="Stripe customer ID")
    status: Optional[str] = Field(None, description="Subscription status")
    plan_tier: str = Field(..., description="Current plan tier")
    current_period_end: Optional[datetime] = Field(
        None,
        description="End of current billing period"
    )
    cancel_at_period_end: Optional[bool] = Field(
        None,
        description="Whether subscription will cancel at period end"
    )
    
    model_config = ConfigDict(from_attributes=True)


class PortalRequest(BaseModel):
    """Request to create a customer portal session."""
    
    return_url: str = Field(
        ...,
        description="URL to return to after portal session"
    )


class PortalResponse(BaseModel):
    """Response containing portal session details."""
    
    url: str = Field(..., description="Customer portal URL")
    
    model_config = ConfigDict(from_attributes=True)


class CancelSubscriptionRequest(BaseModel):
    """Request to cancel a subscription."""
    
    immediately: bool = Field(
        default=False,
        description="Cancel immediately vs at period end"
    )


class WebhookEvent(BaseModel):
    """Stripe webhook event (internal use)."""
    
    event_id: str = Field(..., description="Stripe event ID")
    event_type: str = Field(..., description="Event type (e.g., invoice.paid)")
    data: Dict[str, Any] = Field(..., description="Event data")
    created: int = Field(..., description="Unix timestamp of event")
    
    model_config = ConfigDict(from_attributes=True)


class PriceInfo(BaseModel):
    """Information about a Stripe price."""
    
    price_id: str = Field(..., description="Stripe price ID")
    plan_tier: str = Field(..., description="Plan tier (BASIC, PRO, ENTERPRISE)")
    interval: str = Field(..., description="Billing interval (month, year)")
    
    model_config = ConfigDict(from_attributes=True)

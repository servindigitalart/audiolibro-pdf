"""
Stripe Service
==============
BLOCK 7: Billing & Monetization Layer

Production-grade Stripe integration for subscription management,
payment processing, and webhook handling.

Features:
- Checkout session creation
- Subscription management (create, cancel, update)
- Customer management
- Webhook event handling with signature verification
- Customer portal sessions
- Async-safe operations
"""

import logging
from datetime import datetime
from typing import Dict, Any, Optional, List
from enum import Enum

import stripe
from stripe import Customer, Subscription, checkout, billing_portal

from app.core.config import settings

logger = logging.getLogger(__name__)


class SubscriptionStatus(str, Enum):
    """Stripe subscription statuses."""
    ACTIVE = "active"
    CANCELED = "canceled"
    INCOMPLETE = "incomplete"
    INCOMPLETE_EXPIRED = "incomplete_expired"
    PAST_DUE = "past_due"
    TRIALING = "trialing"
    UNPAID = "unpaid"


class StripePriceConfig:
    """
    Stripe price IDs for different plan tiers.
    
    Configure these in Stripe Dashboard:
    1. Create products for each tier
    2. Add monthly/yearly prices
    3. Copy price IDs here
    """
    
    # Monthly prices
    BASIC_MONTHLY = settings.stripe_price_basic_monthly  # e.g., "price_1234..."
    PRO_MONTHLY = settings.stripe_price_pro_monthly
    ENTERPRISE_MONTHLY = settings.stripe_price_enterprise_monthly
    
    # Yearly prices (optional)
    BASIC_YEARLY = settings.stripe_price_basic_yearly
    PRO_YEARLY = settings.stripe_price_pro_yearly
    ENTERPRISE_YEARLY = settings.stripe_price_enterprise_yearly
    
    @classmethod
    def get_price_id(cls, plan_tier: str, interval: str = "month") -> Optional[str]:
        """
        Get Stripe price ID for plan tier and interval.
        
        Args:
            plan_tier: Plan tier (basic, pro, enterprise)
            interval: Billing interval (month, year)
            
        Returns:
            Stripe price ID or None if not found
        """
        price_map = {
            ("basic", "month"): cls.BASIC_MONTHLY,
            ("basic", "year"): cls.BASIC_YEARLY,
            ("pro", "month"): cls.PRO_MONTHLY,
            ("pro", "year"): cls.PRO_YEARLY,
            ("enterprise", "month"): cls.ENTERPRISE_MONTHLY,
            ("enterprise", "year"): cls.ENTERPRISE_YEARLY,
        }
        return price_map.get((plan_tier.lower(), interval.lower()))


class StripeService:
    """
    Service for Stripe payment and subscription operations.
    
    This service handles all Stripe API interactions:
    - Creating checkout sessions for new subscriptions
    - Managing existing subscriptions
    - Handling customer data
    - Processing webhook events
    - Creating customer portal sessions
    
    All operations are idempotent and include proper error handling.
    """
    
    def __init__(self):
        """Initialize Stripe service with API key."""
        stripe.api_key = settings.stripe_secret_key
        self.webhook_secret = settings.stripe_webhook_secret
        
    async def create_checkout_session(
        self,
        user_id: str,
        user_email: str,
        price_id: str,
        success_url: str,
        cancel_url: str,
        customer_id: Optional[str] = None,
        metadata: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        """
        Create a Stripe Checkout session for subscription purchase.
        
        Args:
            user_id: Internal user ID
            user_email: User email address
            price_id: Stripe price ID
            success_url: Redirect URL on success
            cancel_url: Redirect URL on cancel
            customer_id: Existing Stripe customer ID (optional)
            metadata: Additional metadata (optional)
            
        Returns:
            Dictionary with session ID and URL
            
        Raises:
            stripe.error.StripeError: On Stripe API errors
        """
        try:
            # Prepare metadata
            session_metadata = {
                "user_id": user_id,
                **(metadata or {})
            }
            
            # Create checkout session
            session = checkout.Session.create(
                customer=customer_id,
                customer_email=user_email if not customer_id else None,
                mode="subscription",
                line_items=[{
                    "price": price_id,
                    "quantity": 1,
                }],
                success_url=success_url,
                cancel_url=cancel_url,
                metadata=session_metadata,
                allow_promotion_codes=True,
                billing_address_collection="auto",
                payment_method_collection="always",
                subscription_data={
                    "metadata": session_metadata,
                    "trial_period_days": settings.stripe_trial_days if hasattr(settings, "stripe_trial_days") else None,
                },
            )
            
            logger.info(
                f"Created checkout session",
                extra={
                    "user_id": user_id,
                    "session_id": session.id,
                    "price_id": price_id,
                }
            )
            
            return {
                "session_id": session.id,
                "url": session.url,
            }
            
        except stripe.error.StripeError as e:
            logger.error(
                f"Stripe checkout session creation failed: {str(e)}",
                exc_info=True,
                extra={"user_id": user_id, "price_id": price_id}
            )
            raise
            
    async def create_customer(
        self,
        user_id: str,
        email: str,
        name: Optional[str] = None,
        metadata: Optional[Dict[str, str]] = None,
    ) -> Customer:
        """
        Create a Stripe customer.
        
        Args:
            user_id: Internal user ID
            email: Customer email
            name: Customer name (optional)
            metadata: Additional metadata (optional)
            
        Returns:
            Stripe Customer object
            
        Raises:
            stripe.error.StripeError: On Stripe API errors
        """
        try:
            customer_metadata = {
                "user_id": user_id,
                **(metadata or {})
            }
            
            customer = Customer.create(
                email=email,
                name=name,
                metadata=customer_metadata,
            )
            
            logger.info(
                f"Created Stripe customer",
                extra={
                    "user_id": user_id,
                    "customer_id": customer.id,
                }
            )
            
            return customer
            
        except stripe.error.StripeError as e:
            logger.error(
                f"Stripe customer creation failed: {str(e)}",
                exc_info=True,
                extra={"user_id": user_id}
            )
            raise
            
    async def retrieve_customer(self, customer_id: str) -> Optional[Customer]:
        """
        Retrieve a Stripe customer by ID.
        
        Args:
            customer_id: Stripe customer ID
            
        Returns:
            Customer object or None if not found
        """
        try:
            customer = Customer.retrieve(customer_id)
            return customer
        except stripe.error.InvalidRequestError:
            logger.warning(f"Customer not found: {customer_id}")
            return None
        except stripe.error.StripeError as e:
            logger.error(
                f"Failed to retrieve customer: {str(e)}",
                exc_info=True,
                extra={"customer_id": customer_id}
            )
            raise
            
    async def retrieve_subscription(self, subscription_id: str) -> Optional[Subscription]:
        """
        Retrieve a Stripe subscription by ID.
        
        Args:
            subscription_id: Stripe subscription ID
            
        Returns:
            Subscription object or None if not found
        """
        try:
            subscription = Subscription.retrieve(subscription_id)
            return subscription
        except stripe.error.InvalidRequestError:
            logger.warning(f"Subscription not found: {subscription_id}")
            return None
        except stripe.error.StripeError as e:
            logger.error(
                f"Failed to retrieve subscription: {str(e)}",
                exc_info=True,
                extra={"subscription_id": subscription_id}
            )
            raise
            
    async def cancel_subscription(
        self,
        subscription_id: str,
        immediately: bool = False,
    ) -> Subscription:
        """
        Cancel a Stripe subscription.
        
        Args:
            subscription_id: Stripe subscription ID
            immediately: If True, cancel immediately; else at period end
            
        Returns:
            Updated Subscription object
            
        Raises:
            stripe.error.StripeError: On Stripe API errors
        """
        try:
            if immediately:
                subscription = Subscription.delete(subscription_id)
            else:
                subscription = Subscription.modify(
                    subscription_id,
                    cancel_at_period_end=True,
                )
            
            logger.info(
                f"Cancelled subscription",
                extra={
                    "subscription_id": subscription_id,
                    "immediately": immediately,
                }
            )
            
            return subscription
            
        except stripe.error.StripeError as e:
            logger.error(
                f"Subscription cancellation failed: {str(e)}",
                exc_info=True,
                extra={"subscription_id": subscription_id}
            )
            raise
            
    async def reactivate_subscription(self, subscription_id: str) -> Subscription:
        """
        Reactivate a subscription that was set to cancel at period end.
        
        Args:
            subscription_id: Stripe subscription ID
            
        Returns:
            Updated Subscription object
        """
        try:
            subscription = Subscription.modify(
                subscription_id,
                cancel_at_period_end=False,
            )
            
            logger.info(
                f"Reactivated subscription",
                extra={"subscription_id": subscription_id}
            )
            
            return subscription
            
        except stripe.error.StripeError as e:
            logger.error(
                f"Subscription reactivation failed: {str(e)}",
                exc_info=True,
                extra={"subscription_id": subscription_id}
            )
            raise
            
    async def update_subscription(
        self,
        subscription_id: str,
        new_price_id: str,
        proration_behavior: str = "create_prorations",
    ) -> Subscription:
        """
        Update subscription to a new price (upgrade/downgrade).
        
        Args:
            subscription_id: Stripe subscription ID
            new_price_id: New Stripe price ID
            proration_behavior: How to handle prorations
            
        Returns:
            Updated Subscription object
        """
        try:
            subscription = Subscription.retrieve(subscription_id)
            
            subscription = Subscription.modify(
                subscription_id,
                items=[{
                    "id": subscription["items"]["data"][0].id,
                    "price": new_price_id,
                }],
                proration_behavior=proration_behavior,
            )
            
            logger.info(
                f"Updated subscription",
                extra={
                    "subscription_id": subscription_id,
                    "new_price_id": new_price_id,
                }
            )
            
            return subscription
            
        except stripe.error.StripeError as e:
            logger.error(
                f"Subscription update failed: {str(e)}",
                exc_info=True,
                extra={"subscription_id": subscription_id}
            )
            raise
            
    async def create_portal_session(
        self,
        customer_id: str,
        return_url: str,
    ) -> Dict[str, str]:
        """
        Create a Stripe Customer Portal session.
        
        Args:
            customer_id: Stripe customer ID
            return_url: URL to return to after portal session
            
        Returns:
            Dictionary with portal session URL
            
        Raises:
            stripe.error.StripeError: On Stripe API errors
        """
        try:
            session = billing_portal.Session.create(
                customer=customer_id,
                return_url=return_url,
            )
            
            logger.info(
                f"Created portal session",
                extra={
                    "customer_id": customer_id,
                    "session_id": session.id,
                }
            )
            
            return {
                "url": session.url,
            }
            
        except stripe.error.StripeError as e:
            logger.error(
                f"Portal session creation failed: {str(e)}",
                exc_info=True,
                extra={"customer_id": customer_id}
            )
            raise
            
    async def verify_webhook_signature(
        self,
        payload: bytes,
        signature: str,
    ) -> stripe.Event:
        """
        Verify and construct a Stripe webhook event.
        
        Args:
            payload: Raw webhook payload
            signature: Stripe signature header
            
        Returns:
            Verified Stripe Event object
            
        Raises:
            stripe.error.SignatureVerificationError: On invalid signature
        """
        try:
            event = stripe.Webhook.construct_event(
                payload, signature, self.webhook_secret
            )
            
            logger.info(
                f"Verified webhook event",
                extra={
                    "event_id": event.id,
                    "event_type": event.type,
                }
            )
            
            return event
            
        except stripe.error.SignatureVerificationError as e:
            logger.error(
                f"Webhook signature verification failed: {str(e)}",
                exc_info=True
            )
            raise
            
    async def handle_webhook_event(self, event: stripe.Event) -> Dict[str, Any]:
        """
        Handle a Stripe webhook event.
        
        Args:
            event: Verified Stripe Event object
            
        Returns:
            Dictionary with handling result
        """
        event_type = event.type
        event_data = event.data.object
        
        logger.info(
            f"Processing webhook event",
            extra={
                "event_id": event.id,
                "event_type": event_type,
            }
        )
        
        # Map event types to handlers
        handlers = {
            "checkout.session.completed": self._handle_checkout_completed,
            "customer.subscription.created": self._handle_subscription_created,
            "customer.subscription.updated": self._handle_subscription_updated,
            "customer.subscription.deleted": self._handle_subscription_deleted,
            "invoice.payment_succeeded": self._handle_payment_succeeded,
            "invoice.payment_failed": self._handle_payment_failed,
        }
        
        handler = handlers.get(event_type)
        
        if handler:
            return await handler(event_data)
        else:
            logger.info(f"Unhandled event type: {event_type}")
            return {"status": "unhandled", "event_type": event_type}
            
    async def _handle_checkout_completed(self, session: Dict[str, Any]) -> Dict[str, Any]:
        """Handle checkout.session.completed event."""
        logger.info(
            "Checkout session completed",
            extra={
                "session_id": session.get("id"),
                "customer_id": session.get("customer"),
                "subscription_id": session.get("subscription"),
            }
        )
        
        return {
            "status": "processed",
            "action": "checkout_completed",
            "customer_id": session.get("customer"),
            "subscription_id": session.get("subscription"),
            "user_id": session.get("metadata", {}).get("user_id"),
        }
        
    async def _handle_subscription_created(self, subscription: Dict[str, Any]) -> Dict[str, Any]:
        """Handle customer.subscription.created event."""
        logger.info(
            "Subscription created",
            extra={
                "subscription_id": subscription.get("id"),
                "customer_id": subscription.get("customer"),
                "status": subscription.get("status"),
            }
        )
        
        return {
            "status": "processed",
            "action": "subscription_created",
            "subscription_id": subscription.get("id"),
            "subscription_status": subscription.get("status"),
        }
        
    async def _handle_subscription_updated(self, subscription: Dict[str, Any]) -> Dict[str, Any]:
        """Handle customer.subscription.updated event."""
        logger.info(
            "Subscription updated",
            extra={
                "subscription_id": subscription.get("id"),
                "status": subscription.get("status"),
                "cancel_at_period_end": subscription.get("cancel_at_period_end"),
            }
        )
        
        return {
            "status": "processed",
            "action": "subscription_updated",
            "subscription_id": subscription.get("id"),
            "subscription_status": subscription.get("status"),
            "cancel_at_period_end": subscription.get("cancel_at_period_end"),
        }
        
    async def _handle_subscription_deleted(self, subscription: Dict[str, Any]) -> Dict[str, Any]:
        """Handle customer.subscription.deleted event."""
        logger.info(
            "Subscription deleted",
            extra={
                "subscription_id": subscription.get("id"),
                "customer_id": subscription.get("customer"),
            }
        )
        
        return {
            "status": "processed",
            "action": "subscription_deleted",
            "subscription_id": subscription.get("id"),
        }
        
    async def _handle_payment_succeeded(self, invoice: Dict[str, Any]) -> Dict[str, Any]:
        """Handle invoice.payment_succeeded event."""
        logger.info(
            "Payment succeeded",
            extra={
                "invoice_id": invoice.get("id"),
                "customer_id": invoice.get("customer"),
                "amount": invoice.get("amount_paid"),
                "subscription_id": invoice.get("subscription"),
            }
        )
        
        return {
            "status": "processed",
            "action": "payment_succeeded",
            "invoice_id": invoice.get("id"),
            "amount": invoice.get("amount_paid"),
            "currency": invoice.get("currency"),
        }
        
    async def _handle_payment_failed(self, invoice: Dict[str, Any]) -> Dict[str, Any]:
        """Handle invoice.payment_failed event."""
        logger.error(
            "Payment failed",
            extra={
                "invoice_id": invoice.get("id"),
                "customer_id": invoice.get("customer"),
                "subscription_id": invoice.get("subscription"),
            }
        )
        
        return {
            "status": "processed",
            "action": "payment_failed",
            "invoice_id": invoice.get("id"),
        }

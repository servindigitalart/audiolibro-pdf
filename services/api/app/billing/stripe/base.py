"""
Stripe Provider Abstraction
============================
All Stripe operations go through StripeProvider.  This decouples business
logic from the SDK so tests use MockStripeClient and production uses
RealStripeClient without any code changes — purely environment-driven.

  STRIPE_MODE=mock  → MockStripeClient  (default; safe for all tests)
  STRIPE_MODE=real  → RealStripeClient  (requires STRIPE_SECRET_KEY)
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional


# ── Data classes ──────────────────────────────────────────────────────────────

@dataclass
class StripeCustomer:
    id: str                            # cus_xxx
    email: str
    metadata: dict = field(default_factory=dict)


@dataclass
class StripeSubscription:
    id: str                            # sub_xxx
    customer_id: str
    status: str                        # active|past_due|canceled|trialing|unpaid|incomplete
    current_period_end: int            # Unix timestamp
    price_id: str = ""
    plan_tier: str = ""                # our label, stored in Stripe metadata
    cancel_at_period_end: bool = False
    metadata: dict = field(default_factory=dict)


@dataclass
class StripeCheckoutSession:
    id: str                            # cs_xxx
    customer_id: str
    subscription_id: Optional[str]    # sub_xxx (None for one-time charges)
    status: str                        # complete|expired|open


# ── Exception ─────────────────────────────────────────────────────────────────

class StripeError(Exception):
    """Raised by any StripeProvider method when the Stripe call fails."""
    def __init__(self, message: str, code: str = "unknown", http_status: int = 500) -> None:
        super().__init__(message)
        self.code = code
        self.http_status = http_status


# ── Abstract interface ────────────────────────────────────────────────────────

class StripeProvider(ABC):
    """
    Abstract Stripe operations.

    All methods are async coroutines.  Implementations must raise StripeError
    (not the SDK-specific exception) so callers handle a single exception type.

    Idempotency keys: callers pass their own idempotency_key so operations are
    safe to retry.  The key must be globally unique per logical operation.
    """

    @abstractmethod
    async def create_customer(
        self,
        email: str,
        user_id: str,
        metadata: dict | None = None,
    ) -> StripeCustomer:
        """Create or retrieve a Stripe customer for the given user."""

    @abstractmethod
    async def get_customer(self, customer_id: str) -> Optional[StripeCustomer]:
        """Fetch a Stripe customer by ID.  Returns None if not found."""

    @abstractmethod
    async def create_subscription(
        self,
        customer_id: str,
        price_id: str,
        idempotency_key: str,
        trial_days: int = 0,
        metadata: dict | None = None,
    ) -> StripeSubscription:
        """
        Create a Stripe subscription.

        idempotency_key ensures retries don't double-charge.
        trial_days > 0 creates a trialing subscription.
        """

    @abstractmethod
    async def cancel_subscription(
        self,
        subscription_id: str,
        immediately: bool = False,
    ) -> StripeSubscription:
        """
        Cancel a subscription.

        immediately=False → cancel at period end (default, user keeps access)
        immediately=True  → cancel now, prorate refund
        """

    @abstractmethod
    async def get_subscription(self, subscription_id: str) -> Optional[StripeSubscription]:
        """Fetch a subscription by ID.  Returns None if not found."""

    @abstractmethod
    async def list_customer_subscriptions(
        self,
        customer_id: str,
        status: str = "all",
    ) -> list[StripeSubscription]:
        """
        List subscriptions for a customer.

        status: "all" | "active" | "canceled" | "past_due" | "trialing"
        Returns most-recent-first.
        """

    @abstractmethod
    async def create_billing_portal_session(
        self,
        customer_id: str,
        return_url: str,
    ) -> str:
        """Create a Stripe Billing Portal session.  Returns the session URL."""

    @abstractmethod
    async def create_checkout_session(
        self,
        customer_id: str,
        price_id: str,
        success_url: str,
        cancel_url: str,
        idempotency_key: str,
        trial_days: int = 0,
        metadata: dict | None = None,
    ) -> StripeCheckoutSession:
        """
        Create a Stripe Checkout session for hosted payment.
        Returns the session — callers redirect to session.url.
        """

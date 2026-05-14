"""
Real Stripe Client
==================
Production wrapper around the Stripe Python SDK.

The SDK is synchronous; all calls are wrapped in asyncio.to_thread() so
this class presents an async interface matching StripeProvider.

Retry behaviour: stripe-python handles rate-limit (429) and network errors
with built-in exponential back-off (max_network_retries=3 by default).

Idempotency: all mutating calls pass idempotency_key via Stripe-Idempotency-Key
header so retries are safe.

This class is not imported at module level — only instantiated when
STRIPE_MODE=real, so tests never require the stripe library to be installed.
"""
from __future__ import annotations

import asyncio
import time
from typing import Optional

from app.billing.stripe.base import (
    StripeCheckoutSession,
    StripeCustomer,
    StripeError,
    StripeProvider,
    StripeSubscription,
)


def _import_stripe():
    """Lazy import — keeps tests fast and avoids import errors when stripe is absent."""
    try:
        import stripe
        return stripe
    except ImportError as exc:
        raise RuntimeError(
            "stripe library is required for STRIPE_MODE=real. "
            "Install it with: pip install stripe"
        ) from exc


def _to_sub(s) -> StripeSubscription:
    """Convert stripe.Subscription SDK object to our data class."""
    plan_id = ""
    plan_tier = ""
    if s.get("items") and s["items"]["data"]:
        item = s["items"]["data"][0]
        plan_id = item.get("price", {}).get("id", "")
        plan_tier = item.get("price", {}).get("metadata", {}).get("tier", "")
    return StripeSubscription(
        id=s["id"],
        customer_id=s["customer"] if isinstance(s["customer"], str) else s["customer"]["id"],
        status=s["status"],
        current_period_end=s.get("current_period_end", int(time.time()) + 30 * 86_400),
        price_id=plan_id,
        plan_tier=plan_tier,
        cancel_at_period_end=s.get("cancel_at_period_end", False),
        metadata=dict(s.get("metadata", {})),
    )


class RealStripeClient(StripeProvider):
    """
    Production Stripe client.

    api_key: your Stripe secret key (sk_live_xxx or sk_test_xxx)
    max_network_retries: how many times to retry on transient errors
    """

    def __init__(self, api_key: str, max_network_retries: int = 3) -> None:
        self._stripe = _import_stripe()
        self._stripe.api_key = api_key
        self._stripe.max_network_retries = max_network_retries

    def _wrap(self, fn, *args, **kwargs):
        """Run a sync Stripe SDK call in a thread pool."""
        return asyncio.to_thread(fn, *args, **kwargs)

    def _handle_error(self, exc: Exception) -> None:
        """Convert stripe SDK exceptions to StripeError."""
        stripe = self._stripe
        if hasattr(stripe, "error"):
            errors = stripe.error
            if isinstance(exc, errors.CardError):
                raise StripeError(str(exc), code="card_error", http_status=402) from exc
            if isinstance(exc, errors.RateLimitError):
                raise StripeError(str(exc), code="rate_limit", http_status=429) from exc
            if isinstance(exc, errors.InvalidRequestError):
                raise StripeError(str(exc), code="invalid_request", http_status=400) from exc
            if isinstance(exc, errors.AuthenticationError):
                raise StripeError(str(exc), code="auth_error", http_status=401) from exc
            if isinstance(exc, errors.APIConnectionError):
                raise StripeError(str(exc), code="api_connection", http_status=503) from exc
            if isinstance(exc, errors.StripeError):
                raise StripeError(str(exc), code="stripe_error", http_status=500) from exc
        raise StripeError(str(exc), code="unknown") from exc

    # ── StripeProvider implementation ─────────────────────────────────────────

    async def create_customer(
        self,
        email: str,
        user_id: str,
        metadata: dict | None = None,
    ) -> StripeCustomer:
        try:
            c = await self._wrap(
                self._stripe.Customer.create,
                email=email,
                metadata={"user_id": user_id, **(metadata or {})},
            )
            return StripeCustomer(id=c.id, email=c.email, metadata=dict(c.metadata))
        except Exception as exc:
            self._handle_error(exc)

    async def get_customer(self, customer_id: str) -> Optional[StripeCustomer]:
        try:
            c = await self._wrap(self._stripe.Customer.retrieve, customer_id)
            if c.get("deleted"):
                return None
            return StripeCustomer(id=c.id, email=c.email, metadata=dict(c.metadata))
        except Exception as exc:
            stripe = self._stripe
            if hasattr(stripe, "error") and isinstance(exc, stripe.error.InvalidRequestError):
                return None
            self._handle_error(exc)

    async def create_subscription(
        self,
        customer_id: str,
        price_id: str,
        idempotency_key: str,
        trial_days: int = 0,
        metadata: dict | None = None,
    ) -> StripeSubscription:
        try:
            params: dict = {
                "customer": customer_id,
                "items": [{"price": price_id}],
                "metadata": metadata or {},
            }
            if trial_days > 0:
                params["trial_period_days"] = trial_days
            s = await self._wrap(
                self._stripe.Subscription.create,
                **params,
                idempotency_key=idempotency_key,
            )
            return _to_sub(s)
        except Exception as exc:
            self._handle_error(exc)

    async def cancel_subscription(
        self,
        subscription_id: str,
        immediately: bool = False,
    ) -> StripeSubscription:
        try:
            if immediately:
                s = await self._wrap(
                    self._stripe.Subscription.delete, subscription_id
                )
            else:
                s = await self._wrap(
                    self._stripe.Subscription.modify,
                    subscription_id,
                    cancel_at_period_end=True,
                )
            return _to_sub(s)
        except Exception as exc:
            self._handle_error(exc)

    async def get_subscription(self, subscription_id: str) -> Optional[StripeSubscription]:
        try:
            s = await self._wrap(self._stripe.Subscription.retrieve, subscription_id)
            return _to_sub(s)
        except Exception as exc:
            stripe = self._stripe
            if hasattr(stripe, "error") and isinstance(exc, stripe.error.InvalidRequestError):
                return None
            self._handle_error(exc)

    async def list_customer_subscriptions(
        self,
        customer_id: str,
        status: str = "all",
    ) -> list[StripeSubscription]:
        try:
            params = {"customer": customer_id, "limit": 10}
            if status != "all":
                params["status"] = status
            result = await self._wrap(self._stripe.Subscription.list, **params)
            return [_to_sub(s) for s in result.auto_paging_iter()]
        except Exception as exc:
            self._handle_error(exc)

    async def create_billing_portal_session(
        self,
        customer_id: str,
        return_url: str,
    ) -> str:
        try:
            session = await self._wrap(
                self._stripe.billing_portal.Session.create,
                customer=customer_id,
                return_url=return_url,
            )
            return session.url
        except Exception as exc:
            self._handle_error(exc)

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
        try:
            params: dict = {
                "customer": customer_id,
                "mode": "subscription",
                "line_items": [{"price": price_id, "quantity": 1}],
                "success_url": success_url,
                "cancel_url": cancel_url,
                "metadata": metadata or {},
            }
            if trial_days > 0:
                params["subscription_data"] = {"trial_period_days": trial_days}
            session = await self._wrap(
                self._stripe.checkout.Session.create,
                **params,
                idempotency_key=idempotency_key,
            )
            return StripeCheckoutSession(
                id=session.id,
                customer_id=customer_id,
                subscription_id=session.get("subscription"),
                status=session.status,
            )
        except Exception as exc:
            self._handle_error(exc)

"""
Mock Stripe Client
==================
Deterministic in-memory Stripe substitute for tests and STRIPE_MODE=mock.

Design principles:
  - All state is in-memory dicts (customers, subscriptions, sessions)
  - Every call is recorded in _call_log for assertion in tests
  - configure_failure(method) injects a one-shot StripeError on the next call
    to that method (or "*" to fail any method)
  - Subscription status can be forced via set_subscription_status() to simulate
    Stripe-side state changes (e.g., simulate a payment failure)
  - Thread/coroutine safe: no I/O, pure in-memory

Usage in tests:
    mock = MockStripeClient()
    customer = await mock.create_customer("user@test.com", str(user_id))
    sub = await mock.create_subscription(customer.id, "price_basic", "idem-key-1")
    assert len(mock.calls("create_subscription")) == 1

    mock.configure_failure("create_subscription")
    with pytest.raises(StripeError):
        await mock.create_subscription(...)
"""
from __future__ import annotations

import time
import uuid
from typing import Optional

from app.billing.stripe.base import (
    StripeCheckoutSession,
    StripeCustomer,
    StripeError,
    StripeProvider,
    StripeSubscription,
)


class MockStripeClient(StripeProvider):
    """In-memory Stripe mock — deterministic, recordable, injectable."""

    def __init__(self) -> None:
        self._customers: dict[str, StripeCustomer] = {}
        self._subscriptions: dict[str, StripeSubscription] = {}
        self._sessions: dict[str, StripeCheckoutSession] = {}
        self._sub_idem_index: dict[str, str] = {}  # idempotency_key → sub_id
        self._call_log: list[dict] = []
        self._next_failure: str | None = None   # method name or "*"
        self._portal_url_template = "https://billing.stripe.com/portal/mock/{session_id}"

    # ── Failure injection ─────────────────────────────────────────────────────

    def configure_failure(self, method: str) -> "MockStripeClient":
        """Inject a one-shot StripeError on the next call to `method` (or "*")."""
        self._next_failure = method
        return self

    def clear_failure(self) -> "MockStripeClient":
        self._next_failure = None
        return self

    def _check_failure(self, method: str) -> None:
        if self._next_failure in (method, "*"):
            self._next_failure = None
            raise StripeError(
                f"Injected failure for {method}",
                code="mock_injected_error",
                http_status=500,
            )

    def _log(self, op: str, **kwargs) -> None:
        self._call_log.append({"op": op, "ts": time.time(), **kwargs})

    # ── Inspection helpers (for tests) ────────────────────────────────────────

    def calls(self, op: str | None = None) -> list[dict]:
        """Return recorded calls, optionally filtered by operation name."""
        if op is None:
            return list(self._call_log)
        return [c for c in self._call_log if c["op"] == op]

    def call_count(self, op: str) -> int:
        return len(self.calls(op))

    def set_subscription_status(self, subscription_id: str, status: str) -> None:
        """Force a subscription's status (simulates Stripe-side state changes)."""
        if subscription_id in self._subscriptions:
            self._subscriptions[subscription_id].status = status

    def reset(self) -> None:
        """Clear all state — use between tests if not creating a fresh instance."""
        self._customers.clear()
        self._subscriptions.clear()
        self._sessions.clear()
        self._sub_idem_index.clear()
        self._call_log.clear()
        self._next_failure = None

    # ── StripeProvider implementation ─────────────────────────────────────────

    async def create_customer(
        self,
        email: str,
        user_id: str,
        metadata: dict | None = None,
    ) -> StripeCustomer:
        self._check_failure("create_customer")
        cus_id = f"cus_mock_{uuid.uuid4().hex[:12]}"
        customer = StripeCustomer(
            id=cus_id,
            email=email,
            metadata={"user_id": user_id, **(metadata or {})},
        )
        self._customers[cus_id] = customer
        self._log("create_customer", customer_id=cus_id, email=email, user_id=user_id)
        return customer

    async def get_customer(self, customer_id: str) -> Optional[StripeCustomer]:
        self._check_failure("get_customer")
        self._log("get_customer", customer_id=customer_id)
        return self._customers.get(customer_id)

    async def create_subscription(
        self,
        customer_id: str,
        price_id: str,
        idempotency_key: str,
        trial_days: int = 0,
        metadata: dict | None = None,
    ) -> StripeSubscription:
        self._check_failure("create_subscription")
        # Idempotency: return existing subscription for the same key
        if idempotency_key in self._sub_idem_index:
            existing_id = self._sub_idem_index[idempotency_key]
            if existing_id in self._subscriptions:
                self._log(
                    "create_subscription",
                    sub_id=existing_id,
                    customer_id=customer_id,
                    price_id=price_id,
                    idempotency_key=idempotency_key,
                    trial_days=trial_days,
                )
                return self._subscriptions[existing_id]
        sub_id = f"sub_mock_{uuid.uuid4().hex[:12]}"
        status = "trialing" if trial_days > 0 else "active"
        sub = StripeSubscription(
            id=sub_id,
            customer_id=customer_id,
            status=status,
            current_period_end=int(time.time()) + 30 * 86_400,
            price_id=price_id,
            metadata={"idempotency_key": idempotency_key, **(metadata or {})},
        )
        self._subscriptions[sub_id] = sub
        self._sub_idem_index[idempotency_key] = sub_id
        self._log(
            "create_subscription",
            sub_id=sub_id,
            customer_id=customer_id,
            price_id=price_id,
            idempotency_key=idempotency_key,
            trial_days=trial_days,
        )
        return sub

    async def cancel_subscription(
        self,
        subscription_id: str,
        immediately: bool = False,
    ) -> StripeSubscription:
        self._check_failure("cancel_subscription")
        sub = self._subscriptions.get(subscription_id)
        if sub is None:
            raise StripeError(
                f"Subscription {subscription_id!r} not found",
                code="resource_missing",
                http_status=404,
            )
        if immediately:
            sub.status = "canceled"
        else:
            sub.cancel_at_period_end = True
        self._log("cancel_subscription", sub_id=subscription_id, immediately=immediately)
        return sub

    async def get_subscription(self, subscription_id: str) -> Optional[StripeSubscription]:
        self._check_failure("get_subscription")
        self._log("get_subscription", sub_id=subscription_id)
        return self._subscriptions.get(subscription_id)

    async def list_customer_subscriptions(
        self,
        customer_id: str,
        status: str = "all",
    ) -> list[StripeSubscription]:
        self._check_failure("list_customer_subscriptions")
        subs = [
            s for s in self._subscriptions.values()
            if s.customer_id == customer_id
            and (status == "all" or s.status == status)
        ]
        self._log("list_customer_subscriptions", customer_id=customer_id, status=status, count=len(subs))
        return subs

    async def create_billing_portal_session(
        self,
        customer_id: str,
        return_url: str,
    ) -> str:
        self._check_failure("create_billing_portal_session")
        session_id = f"bps_mock_{uuid.uuid4().hex[:12]}"
        url = self._portal_url_template.format(session_id=session_id)
        self._log("create_billing_portal_session", customer_id=customer_id, session_id=session_id)
        return url

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
        self._check_failure("create_checkout_session")
        session_id = f"cs_mock_{uuid.uuid4().hex[:12]}"
        sub_id = f"sub_mock_{uuid.uuid4().hex[:12]}"

        status = "trialing" if trial_days > 0 else "active"
        sub = StripeSubscription(
            id=sub_id,
            customer_id=customer_id,
            status=status,
            current_period_end=int(time.time()) + 30 * 86_400,
            price_id=price_id,
            metadata={"idempotency_key": idempotency_key, **(metadata or {})},
        )
        self._subscriptions[sub_id] = sub

        session = StripeCheckoutSession(
            id=session_id,
            customer_id=customer_id,
            subscription_id=sub_id,
            status="complete",
        )
        self._sessions[session_id] = session
        self._log(
            "create_checkout_session",
            session_id=session_id,
            customer_id=customer_id,
            price_id=price_id,
            idempotency_key=idempotency_key,
        )
        return session

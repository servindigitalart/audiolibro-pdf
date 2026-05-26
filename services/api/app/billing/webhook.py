"""
Billing Engine — Webhook Service
==================================
Stripe-compatible webhook handling with:
  - HMAC-SHA256 signature validation
  - DB-persisted idempotency (dedup by stripe_event_id)
  - Idempotent event processing (re-processing a delivered event is safe)
  - Replay support (replay a stored event for debugging)

Design: WebhookService.process() is the single entry point.  It always
persists the raw payload before dispatching, so even if processing fails the
event is never silently lost.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Awaitable, Optional

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

import logging

from app.billing.constants import WebhookEventType
from app.billing.models import WebhookEvent
from app.billing.subscription import SubscriptionService, InvalidTransition
from app.billing.constants import SubscriptionStatus

logger = logging.getLogger(__name__)


def _price_id_to_tier(price_id: str) -> str:
    """Map a Stripe price ID to our uppercase PlanTier string. Returns '' if unknown."""
    if not price_id:
        return ""
    from app.core.config import settings
    mapping = {
        settings.stripe_price_basic_monthly:      "BASIC",
        settings.stripe_price_basic_yearly:       "BASIC",
        settings.stripe_price_pro_monthly:        "PRO",
        settings.stripe_price_pro_yearly:         "PRO",
        settings.stripe_price_enterprise_monthly: "ENTERPRISE",
        settings.stripe_price_enterprise_yearly:  "ENTERPRISE",
    }
    return mapping.get(price_id, "")


class InvalidSignature(Exception):
    """Stripe webhook signature validation failed."""


class WebhookService:
    """
    Processes inbound Stripe webhooks.

    Signature validation is Stripe-compatible: the signed payload is
    ``{timestamp}.{body}`` and the expected signature is one of the
    ``v1=<hex>`` values in the ``Stripe-Signature`` header.
    """

    def __init__(self, session: AsyncSession, webhook_secret: str = "") -> None:
        self._session = session
        self._secret = webhook_secret

    # ── Public API ────────────────────────────────────────────────────────────

    def verify_signature(self, payload: bytes, stripe_signature: str) -> None:
        """
        Validate the Stripe-Signature header.

        Raises InvalidSignature on failure.
        """
        if not self._secret:
            return  # No secret configured → skip (test/dev mode)

        try:
            parts = {k: v for k, v in (p.split("=", 1) for p in stripe_signature.split(","))}
            timestamp = parts["t"]
            signatures = [v for k, v in parts.items() if k.startswith("v1")]
        except (ValueError, KeyError) as exc:
            raise InvalidSignature("Malformed Stripe-Signature header") from exc

        # Reject events older than 5 minutes (replay protection)
        age = int(time.time()) - int(timestamp)
        if age > 300:
            raise InvalidSignature(f"Webhook timestamp too old: {age}s")

        signed = f"{timestamp}.{payload.decode()}"
        expected = hmac.new(
            self._secret.encode(), signed.encode(), hashlib.sha256
        ).hexdigest()

        if not any(hmac.compare_digest(expected, sig) for sig in signatures):
            raise InvalidSignature("Signature mismatch")

    async def process(
        self,
        raw_payload: bytes,
        stripe_signature: str = "",
    ) -> WebhookEvent:
        """
        Validate, persist, and dispatch a webhook event.

        Always returns the WebhookEvent row.  If the event was already
        processed (dedup), the existing row is returned without re-processing.
        """
        if stripe_signature:
            self.verify_signature(raw_payload, stripe_signature)

        data = json.loads(raw_payload)
        event_id = data.get("id", str(uuid.uuid4()))
        event_type = data.get("type", "unknown")

        logger.info("[SONORO] stripe_webhook_received type=%s event_id=%s", event_type, event_id)

        # Dedup: if already processed, return existing row
        existing = await self._get_event(event_id)
        if existing is not None:
            if existing.status == "processed":
                return existing
            # If pending/failed, allow re-processing

        # Persist before dispatching
        event = await self._upsert_event(event_id, event_type, raw_payload.decode())

        try:
            await self._dispatch(event_type, data, event)
            await self._mark_processed(event)
        except Exception as exc:
            await self._mark_failed(event, str(exc))
            raise

        return event

    async def replay(self, stripe_event_id: str) -> WebhookEvent:
        """Re-process a stored event (useful for debugging failed webhooks)."""
        event = await self._get_event(stripe_event_id)
        if event is None:
            raise ValueError(f"Event {stripe_event_id!r} not found")

        data = json.loads(event.payload)
        await self._session.execute(
            update(WebhookEvent)
            .where(WebhookEvent.stripe_event_id == stripe_event_id)
            .values(status="replayed", attempts=WebhookEvent.attempts + 1)
        )
        await self._session.commit()

        try:
            await self._dispatch(event.event_type, data, event)
            await self._mark_processed(event)
        except Exception as exc:
            await self._mark_failed(event, str(exc))
            raise

        return event

    # ── Event dispatch ────────────────────────────────────────────────────────

    async def _dispatch(self, event_type: str, data: dict, event: WebhookEvent) -> None:
        handlers = {
            WebhookEventType.CHECKOUT_SESSION_COMPLETED:            self._on_checkout_completed,
            WebhookEventType.INVOICE_PAID:                          self._on_invoice_paid,
            WebhookEventType.INVOICE_PAYMENT_FAILED:                self._on_payment_failed,
            WebhookEventType.CUSTOMER_SUBSCRIPTION_UPDATED:         self._on_subscription_updated,
            WebhookEventType.CUSTOMER_SUBSCRIPTION_DELETED:         self._on_subscription_deleted,
            WebhookEventType.CUSTOMER_SUBSCRIPTION_TRIAL_ENDING:    self._on_trial_ending,
        }
        handler = handlers.get(event_type)
        if handler:
            await handler(data, event)

    async def _on_checkout_completed(self, data: dict, event: WebhookEvent) -> None:
        """
        checkout.session.completed: customer completed Stripe-hosted checkout.

        Links the Stripe subscription_id to the user row, transitions the
        subscription to ACTIVE, and updates plan_tier from session metadata.
        Safe to replay — transition is idempotent.
        """
        from sqlalchemy import update as sa_update
        from app.db.models.user import User

        session_obj = data.get("data", {}).get("object", {})
        customer_id = session_obj.get("customer")
        subscription_id = session_obj.get("subscription")
        tier = session_obj.get("metadata", {}).get("tier", "")

        if not customer_id:
            return

        user = await self._find_user_by_stripe_customer(customer_id)
        if user is None:
            return

        old_plan = user.plan_tier

        updates: dict = {}
        if subscription_id and user.stripe_subscription_id != subscription_id:
            updates["stripe_subscription_id"] = subscription_id
        if tier and tier in ("BASIC", "PRO", "ENTERPRISE"):
            updates["plan_tier"] = tier
        if updates:
            await self._session.execute(
                sa_update(User).where(User.id == user.id).values(**updates)
            )
            await self._session.commit()

        svc = SubscriptionService(self._session)
        try:
            await svc.transition(
                user.id,
                SubscriptionStatus.ACTIVE,
                reason="checkout.session.completed",
                actor="stripe",
                stripe_event_id=event.stripe_event_id,
            )
        except InvalidTransition:
            pass  # Already active — idempotent

        logger.info(
            "[SONORO] stripe_webhook_checkout_completed user_id=%s old_plan=%s new_plan=%s sub_id=%s",
            user.id, old_plan, tier or old_plan, subscription_id,
        )

    async def _on_invoice_paid(self, data: dict, event: WebhookEvent) -> None:
        sub_obj = data.get("data", {}).get("object", {})
        customer_id = sub_obj.get("customer")
        if not customer_id:
            return
        user = await self._find_user_by_stripe_customer(customer_id)
        if user is None:
            return
        svc = SubscriptionService(self._session)
        try:
            await svc.transition(
                user.id,
                SubscriptionStatus.ACTIVE,
                reason="invoice.paid",
                actor="stripe",
                stripe_event_id=event.stripe_event_id,
            )
        except InvalidTransition:
            pass  # Already active — idempotent

    async def _on_payment_failed(self, data: dict, event: WebhookEvent) -> None:
        sub_obj = data.get("data", {}).get("object", {})
        customer_id = sub_obj.get("customer")
        if not customer_id:
            return
        user = await self._find_user_by_stripe_customer(customer_id)
        if user is None:
            return
        svc = SubscriptionService(self._session)
        try:
            await svc.transition(
                user.id,
                SubscriptionStatus.PAST_DUE,
                reason="invoice.payment_failed",
                actor="stripe",
                stripe_event_id=event.stripe_event_id,
            )
        except InvalidTransition:
            pass

    async def _on_subscription_updated(self, data: dict, event: WebhookEvent) -> None:
        from sqlalchemy import update as sa_update
        from app.db.models.user import User

        sub_obj = data.get("data", {}).get("object", {})
        stripe_status = sub_obj.get("status", "")
        customer_id = sub_obj.get("customer")
        if not customer_id:
            return
        user = await self._find_user_by_stripe_customer(customer_id)
        if user is None:
            return

        old_plan = user.plan_tier

        # Derive plan_tier from price_id in subscription items
        items = sub_obj.get("items", {}).get("data", [])
        price_id = items[0].get("price", {}).get("id", "") if items else ""
        tier = _price_id_to_tier(price_id)
        if tier and tier != user.plan_tier:
            await self._session.execute(
                sa_update(User).where(User.id == user.id).values(plan_tier=tier)
            )
            await self._session.commit()

        status_map = {
            "active":   SubscriptionStatus.ACTIVE,
            "past_due": SubscriptionStatus.PAST_DUE,
            "canceled": SubscriptionStatus.CANCELED,
            "trialing": SubscriptionStatus.TRIAL,
            "unpaid":   SubscriptionStatus.SUSPENDED,
        }
        to_status = status_map.get(stripe_status)
        if to_status is None:
            return

        svc = SubscriptionService(self._session)
        try:
            await svc.transition(
                user.id,
                to_status,
                reason=f"subscription.updated status={stripe_status}",
                actor="stripe",
                stripe_event_id=event.stripe_event_id,
            )
        except InvalidTransition:
            pass

        logger.info(
            "[SONORO] subscription_updated user_id=%s old_plan=%s new_plan=%s status=%s",
            user.id, old_plan, tier or old_plan, stripe_status,
        )

    async def _on_subscription_deleted(self, data: dict, event: WebhookEvent) -> None:
        from sqlalchemy import update as sa_update
        from app.db.models.user import User

        sub_obj = data.get("data", {}).get("object", {})
        customer_id = sub_obj.get("customer")
        if not customer_id:
            return
        user = await self._find_user_by_stripe_customer(customer_id)
        if user is None:
            return

        old_plan = user.plan_tier

        # Reset to FREE on subscription deletion
        await self._session.execute(
            sa_update(User)
            .where(User.id == user.id)
            .values(plan_tier="FREE", stripe_subscription_id=None)
        )
        await self._session.commit()

        svc = SubscriptionService(self._session)
        try:
            await svc.transition(
                user.id,
                SubscriptionStatus.CANCELED,
                reason="subscription.deleted",
                actor="stripe",
                stripe_event_id=event.stripe_event_id,
            )
        except InvalidTransition:
            pass

        logger.info(
            "[SONORO] subscription_deleted user_id=%s old_plan=%s new_plan=FREE",
            user.id, old_plan,
        )

    async def _on_trial_ending(self, data: dict, event: WebhookEvent) -> None:
        pass  # Notify user — no state change required

    # ── DB helpers ────────────────────────────────────────────────────────────

    async def _get_event(self, stripe_event_id: str) -> Optional[WebhookEvent]:
        result = await self._session.execute(
            select(WebhookEvent).where(WebhookEvent.stripe_event_id == stripe_event_id)
        )
        return result.scalar_one_or_none()

    async def _upsert_event(self, event_id: str, event_type: str, payload: str) -> WebhookEvent:
        existing = await self._get_event(event_id)
        if existing:
            return existing
        event = WebhookEvent(
            stripe_event_id=event_id,
            event_type=event_type,
            payload=payload,
            status="pending",
            attempts=1,
        )
        self._session.add(event)
        try:
            await self._session.commit()
            await self._session.refresh(event)
        except IntegrityError:
            await self._session.rollback()
            existing = await self._get_event(event_id)
            return existing
        return event

    async def _mark_processed(self, event: WebhookEvent) -> None:
        await self._session.execute(
            update(WebhookEvent)
            .where(WebhookEvent.stripe_event_id == event.stripe_event_id)
            .values(status="processed", processed_at=datetime.now(timezone.utc))
        )
        await self._session.commit()

    async def _mark_failed(self, event: WebhookEvent, error: str) -> None:
        await self._session.execute(
            update(WebhookEvent)
            .where(WebhookEvent.stripe_event_id == event.stripe_event_id)
            .values(status="failed", error_message=error[:500])
        )
        await self._session.commit()

    async def _find_user_by_stripe_customer(self, customer_id: str):
        from app.db.models.user import User
        from sqlalchemy import select as sa_select
        result = await self._session.execute(
            sa_select(User).where(User.stripe_customer_id == customer_id)
        )
        return result.scalar_one_or_none()

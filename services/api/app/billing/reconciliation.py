"""
Billing Engine — Subscription Reconciliation Service
======================================================
Stripe is the PRIMARY source of truth for subscription state.
The local DB is a cached projection that must be kept in sync.

Reconciliation detects and corrects drift between Stripe and the local DB:
  - Stripe says "active"   but DB says "canceled" → sync to active
  - Stripe says "past_due" but DB says "active"   → sync to past_due
  - No Stripe subscription  but DB says "active"  → sync to canceled

When to run:
  - On demand (admin API)
  - After a webhook delivery failure
  - Periodically (e.g., every hour via Celery beat)

Design:
  - READ-ONLY from Stripe; writes only go to the DB via the existing
    SubscriptionService.transition() so all changes are audit-logged
  - Returns structured ReconciliationResult for monitoring
  - Never raises on Stripe API error — returns an error result instead
    so a single unreachable customer does not abort a bulk run
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.billing.constants import SubscriptionStatus
from app.billing.stripe.base import StripeProvider
from app.billing.subscription import InvalidTransition, SubscriptionService
from app.db.models.user import User


# ── Stripe → local status mapping ────────────────────────────────────────────

_STRIPE_TO_LOCAL: dict[str, str] = {
    "active":             SubscriptionStatus.ACTIVE.value,
    "past_due":           SubscriptionStatus.PAST_DUE.value,
    "canceled":           SubscriptionStatus.CANCELED.value,
    "trialing":           SubscriptionStatus.TRIAL.value,
    "unpaid":             SubscriptionStatus.SUSPENDED.value,
    "incomplete":         SubscriptionStatus.PAST_DUE.value,
    "incomplete_expired": SubscriptionStatus.CANCELED.value,
    "paused":             SubscriptionStatus.SUSPENDED.value,
}


# ── Result type ───────────────────────────────────────────────────────────────

@dataclass
class ReconciliationResult:
    user_id: uuid.UUID
    outcome: str                  # "ok" | "synced" | "no_stripe_customer" | "no_subscriptions" | "error"
    drift_detected: bool = False
    previous_status: str = ""
    new_status: str = ""
    stripe_subscription_id: str = ""
    stripe_status: str = ""
    detail: str = ""
    reconciled_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    @property
    def is_ok(self) -> bool:
        return self.outcome in ("ok", "no_stripe_customer", "no_subscriptions")


@dataclass
class BulkReconciliationReport:
    run_at: str
    total_users: int
    users_checked: int
    synced: int
    errors: int
    results: list[ReconciliationResult]

    @property
    def drift_rate(self) -> float:
        if self.users_checked == 0:
            return 0.0
        return round(self.synced / self.users_checked, 4)


# ── Service ───────────────────────────────────────────────────────────────────

class ReconciliationService:
    """
    Reconciles local subscription state against Stripe as source of truth.

    All DB writes go through SubscriptionService.transition() so every
    reconciliation-driven change appears in the subscription_audit_log.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ── Public API ────────────────────────────────────────────────────────────

    async def reconcile_user(
        self,
        user: User,
        stripe: StripeProvider,
    ) -> ReconciliationResult:
        """
        Check and correct a single user's subscription state.

        Never raises — all errors are captured in the result.
        """
        if not user.stripe_customer_id:
            return ReconciliationResult(
                user_id=user.id,
                outcome="no_stripe_customer",
                detail="user has no stripe_customer_id",
            )

        try:
            subscriptions = await stripe.list_customer_subscriptions(user.stripe_customer_id)
        except Exception as exc:
            return ReconciliationResult(
                user_id=user.id,
                outcome="error",
                detail=f"Stripe API error: {exc}",
            )

        if not subscriptions:
            local_status = user.subscription_status or "free"
            if local_status not in ("free", "canceled"):
                return await self._sync(
                    user,
                    stripe_sub_id="",
                    stripe_status="",
                    target_local=SubscriptionStatus.CANCELED.value,
                    reason="reconciliation: no stripe subscriptions found",
                    previous_status=local_status,
                    outcome_tag="synced",
                )
            return ReconciliationResult(
                user_id=user.id, outcome="no_subscriptions"
            )

        # Pick the most relevant subscription: active > trialing > most recent
        priority_order = ["active", "trialing", "past_due", "unpaid", "incomplete"]
        best_sub = None
        for status_priority in priority_order:
            best_sub = next((s for s in subscriptions if s.status == status_priority), None)
            if best_sub:
                break
        if best_sub is None:
            best_sub = subscriptions[0]  # fallback: most recently created

        expected_local = _STRIPE_TO_LOCAL.get(best_sub.status)
        if expected_local is None:
            return ReconciliationResult(
                user_id=user.id,
                outcome="ok",
                stripe_subscription_id=best_sub.id,
                stripe_status=best_sub.status,
                detail=f"unrecognized stripe status {best_sub.status!r} — skipping",
            )

        local_status = user.subscription_status or "free"
        if local_status == expected_local:
            return ReconciliationResult(
                user_id=user.id,
                outcome="ok",
                stripe_subscription_id=best_sub.id,
                stripe_status=best_sub.status,
            )

        # Drift detected — sync DB to match Stripe
        return await self._sync(
            user,
            stripe_sub_id=best_sub.id,
            stripe_status=best_sub.status,
            target_local=expected_local,
            reason=f"reconciliation: stripe={best_sub.status} local={local_status}",
            previous_status=local_status,
            outcome_tag="synced",
        )

    async def reconcile_bulk(
        self,
        stripe: StripeProvider,
        limit: int = 200,
    ) -> BulkReconciliationReport:
        """
        Reconcile the most recently active users (up to `limit`).

        Returns a report summarising all reconciliation outcomes.
        """
        result = await self._session.execute(
            select(User)
            .where(User.stripe_customer_id.isnot(None))
            .order_by(User.updated_at.desc())
            .limit(limit)
        )
        users = list(result.scalars())

        total_result = await self._session.execute(
            select(func.count()).select_from(User)
        )
        total_users = total_result.scalar_one() or 0

        results: list[ReconciliationResult] = []
        for user in users:
            r = await self.reconcile_user(user, stripe)
            results.append(r)

        return BulkReconciliationReport(
            run_at=datetime.now(timezone.utc).isoformat(),
            total_users=total_users,
            users_checked=len(users),
            synced=sum(1 for r in results if r.outcome == "synced"),
            errors=sum(1 for r in results if r.outcome == "error"),
            results=results,
        )

    # ── Internal ──────────────────────────────────────────────────────────────

    async def _sync(
        self,
        user: User,
        stripe_sub_id: str,
        stripe_status: str,
        target_local: str,
        reason: str,
        previous_status: str,
        outcome_tag: str,
    ) -> ReconciliationResult:
        svc = SubscriptionService(self._session)
        try:
            await svc.transition(
                user.id,
                SubscriptionStatus(target_local),
                reason=reason,
                actor="reconciliation",
            )
        except InvalidTransition as exc:
            return ReconciliationResult(
                user_id=user.id,
                outcome="error",
                stripe_subscription_id=stripe_sub_id,
                stripe_status=stripe_status,
                previous_status=previous_status,
                new_status=target_local,
                detail=f"InvalidTransition: {exc}",
                drift_detected=True,
            )
        except Exception as exc:
            return ReconciliationResult(
                user_id=user.id,
                outcome="error",
                stripe_subscription_id=stripe_sub_id,
                stripe_status=stripe_status,
                detail=str(exc),
                drift_detected=True,
            )

        return ReconciliationResult(
            user_id=user.id,
            outcome=outcome_tag,
            drift_detected=True,
            stripe_subscription_id=stripe_sub_id,
            stripe_status=stripe_status,
            previous_status=previous_status,
            new_status=target_local,
        )

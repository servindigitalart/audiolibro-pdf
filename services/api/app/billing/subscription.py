"""
Billing Engine — Subscription State Machine
============================================
All state transitions must go through SubscriptionService.transition().
Invalid transitions raise InvalidTransition — the caller decides the HTTP response.

The state machine is deterministic: given (current_status, to_status) there is
exactly one outcome.  All transitions are persisted to subscription_audit_log
before the users table is updated so the audit trail is always complete.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.billing.constants import SubscriptionStatus, VALID_TRANSITIONS
from app.billing.models import SubscriptionAuditLog
from app.db.models.user import User


class InvalidTransition(Exception):
    """Raised when a requested state transition is not in VALID_TRANSITIONS."""

    def __init__(self, from_status: str, to_status: str) -> None:
        super().__init__(f"Transition {from_status!r} → {to_status!r} is not allowed")
        self.from_status = from_status
        self.to_status = to_status


class SubscriptionService:
    """
    Validates and persists subscription state transitions.

    Usage:
        svc = SubscriptionService(session)
        await svc.transition(user_id, SubscriptionStatus.ACTIVE, reason="payment received")
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ── Public API ────────────────────────────────────────────────────────────

    async def transition(
        self,
        user_id: uuid.UUID,
        to_status: SubscriptionStatus,
        *,
        reason: Optional[str] = None,
        actor: str = "system",
        stripe_event_id: Optional[str] = None,
    ) -> SubscriptionAuditLog:
        """
        Validate and apply a subscription state transition.

        Raises InvalidTransition if the transition is not permitted.
        Returns the SubscriptionAuditLog row that was created.
        """
        user = await self._get_user(user_id)
        current_raw = user.subscription_status or SubscriptionStatus.FREE.value
        current = SubscriptionStatus(current_raw)

        if to_status not in VALID_TRANSITIONS.get(current, frozenset()):
            raise InvalidTransition(current.value, to_status.value)

        log = SubscriptionAuditLog(
            user_id=user_id,
            from_status=current.value,
            to_status=to_status.value,
            reason=reason,
            actor=actor,
            stripe_event_id=stripe_event_id,
        )
        self._session.add(log)

        await self._session.execute(
            update(User)
            .where(User.id == user_id)
            .values(subscription_status=to_status.value)
        )
        await self._session.commit()
        await self._session.refresh(log)
        return log

    async def get_status(self, user_id: uuid.UUID) -> SubscriptionStatus:
        user = await self._get_user(user_id)
        raw = user.subscription_status or SubscriptionStatus.FREE.value
        return SubscriptionStatus(raw)

    async def history(self, user_id: uuid.UUID, limit: int = 50) -> list[SubscriptionAuditLog]:
        result = await self._session.execute(
            select(SubscriptionAuditLog)
            .where(SubscriptionAuditLog.user_id == user_id)
            .order_by(SubscriptionAuditLog.created_at.desc())
            .limit(limit)
        )
        return list(result.scalars())

    # ── Internal ──────────────────────────────────────────────────────────────

    async def _get_user(self, user_id: uuid.UUID) -> User:
        result = await self._session.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        if user is None:
            raise ValueError(f"User {user_id} not found")
        return user

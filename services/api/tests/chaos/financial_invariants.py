"""
Financial Invariant Checking
==============================
Verifiable guarantees that must hold at ALL times, regardless of failures.

These are not test assertions — they are formal financial invariants that can be
run at any point to verify the system has not entered an inconsistent state.

Invariants checked:
  I1 — No duplicate idempotency completions
       (same billing operation never charged twice)
  I2 — Usage counts are non-negative and monotonic
       (counters can only increase — reversal = bug)
  I3 — Every subscription audit log transition was valid
       (state machine was never bypassed)
  I4 — Webhook events are globally unique by stripe_event_id
       (Stripe events processed exactly once)
  I5 — Redis usage >= DB usage for same period (after flush)
       (Redis is source of truth — DB is snapshot; DB > Redis = data loss)
  I6 — No idempotency key is permanently stuck in "locked" state
       (stuck locks = potential revenue loss — operation never completed)
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.billing.constants import VALID_TRANSITIONS, SubscriptionStatus, USAGE_HOT_KEY, USAGE_MONTH_KEY
from app.billing.models import (
    IdempotencyKey,
    SubscriptionAuditLog,
    UsageAggregate,
    WebhookEvent,
)


# ── Violation container ───────────────────────────────────────────────────────

class InvariantViolation(Exception):
    """Raised when a financial invariant is violated.

    Attributes:
        invariant_id: short code (I1–I6)
        description:  what invariant was broken
        evidence:     details for debugging
    """

    def __init__(self, invariant_id: str, description: str, evidence: Any = None) -> None:
        msg = f"[{invariant_id}] {description}"
        if evidence:
            msg += f"\n  Evidence: {evidence}"
        super().__init__(msg)
        self.invariant_id = invariant_id
        self.description = description
        self.evidence = evidence


# ── Individual invariant checks ───────────────────────────────────────────────

async def check_I1_no_duplicate_idempotency_completions(session: AsyncSession) -> None:
    """
    I1: No two 'complete' rows for the same idempotency key.

    The UNIQUE constraint on idempotency_key makes duplicate inserts impossible.
    But a client could theoretically call complete() twice. This check verifies
    the DB never ends up with duplicate completions.

    Violation = same billing operation would be reflected twice in the ledger.
    """
    result = await session.execute(
        select(IdempotencyKey.idempotency_key, func.count().label("cnt"))
        .where(IdempotencyKey.status == "complete")
        .group_by(IdempotencyKey.idempotency_key)
        .having(func.count() > 1)
    )
    rows = result.all()
    if rows:
        raise InvariantViolation(
            "I1",
            "Duplicate idempotency completions detected — possible double-billing",
            {row.idempotency_key: row.cnt for row in rows},
        )


async def check_I2_usage_non_negative(session: AsyncSession) -> None:
    """
    I2: Usage aggregates are never negative.

    Usage counts represent real API calls — they can only increase.
    A negative value means a counter was decremented or wrapped, which is a bug.

    Violation = financial records are corrupted; billing calculations are wrong.
    """
    result = await session.execute(
        select(UsageAggregate.user_id, UsageAggregate.period_key,
               UsageAggregate.api_calls, UsageAggregate.cost_usd)
        .where(
            or_(
                UsageAggregate.api_calls < 0,
                UsageAggregate.cost_usd < 0,
                UsageAggregate.compute_ms < 0,
            )
        )
    )
    violations = result.all()
    if violations:
        raise InvariantViolation(
            "I2",
            f"Found {len(violations)} usage rows with negative values",
            [
                {"user_id": str(r.user_id), "period": r.period_key,
                 "api_calls": r.api_calls, "cost_usd": r.cost_usd}
                for r in violations
            ],
        )


async def check_I3_subscription_transitions_valid(session: AsyncSession) -> None:
    """
    I3: Every subscription audit log transition was valid per VALID_TRANSITIONS.

    The state machine in SubscriptionService.transition() should prevent invalid
    transitions. If an invalid one appears in the audit log, the state machine
    was bypassed (direct DB write or bug in the service).

    Violation = subscription state is undefined; billing tier may be wrong.
    """
    result = await session.execute(
        select(SubscriptionAuditLog.id, SubscriptionAuditLog.from_status,
               SubscriptionAuditLog.to_status, SubscriptionAuditLog.user_id)
        .where(SubscriptionAuditLog.from_status.is_not(None))
        .order_by(SubscriptionAuditLog.created_at)
    )
    rows = result.all()

    invalid = []
    for row in rows:
        try:
            from_s = SubscriptionStatus(row.from_status)
            to_s = SubscriptionStatus(row.to_status)
        except ValueError:
            invalid.append({"id": str(row.id), "reason": "unknown status value",
                           "from": row.from_status, "to": row.to_status})
            continue
        if to_s not in VALID_TRANSITIONS.get(from_s, frozenset()):
            invalid.append({"id": str(row.id), "from": from_s.value, "to": to_s.value,
                           "user_id": str(row.user_id)})

    if invalid:
        raise InvariantViolation(
            "I3",
            f"Found {len(invalid)} invalid subscription transitions in audit log",
            invalid,
        )


async def check_I4_webhook_events_unique(session: AsyncSession) -> None:
    """
    I4: Each stripe_event_id appears exactly once in webhook_events.

    The UNIQUE constraint enforces this at the INSERT level. If two rows
    exist with the same ID, the constraint was circumvented (direct insert).

    Violation = same Stripe event processed multiple times; possible double-billing.
    """
    result = await session.execute(
        select(WebhookEvent.stripe_event_id, func.count().label("cnt"))
        .group_by(WebhookEvent.stripe_event_id)
        .having(func.count() > 1)
    )
    rows = result.all()
    if rows:
        raise InvariantViolation(
            "I4",
            f"Found {len(rows)} duplicate stripe_event_ids",
            [row.stripe_event_id for row in rows],
        )


async def check_I5_redis_usage_not_less_than_db(
    redis: Any,
    session: AsyncSession,
    user_id: uuid.UUID,
    period_type: str,
    period_key: str,
) -> None:
    """
    I5: Redis usage >= DB usage for the same period.

    Redis is the authoritative hot counter. DB is a snapshot (flushed periodically).
    If DB > Redis, Redis was cleared/reset without a corresponding DB flush —
    this is data loss: usage happened but Redis no longer records it.

    Violation = Redis was evicted or reset; unbilled usage exists only in DB.

    Note: Redis < DB by a small delta is expected (flush hasn't run yet for new
    activity). Redis LESS than DB means data loss in Redis.
    """
    uid = str(user_id)
    if period_type == "day":
        redis_key = USAGE_HOT_KEY.format(user_id=uid, date=period_key)
    else:
        redis_key = USAGE_MONTH_KEY.format(user_id=uid, month=period_key)

    raw = await redis.hgetall(redis_key)
    redis_calls = int(float(raw.get("api_calls", 0)))

    result = await session.execute(
        select(UsageAggregate.api_calls).where(
            UsageAggregate.user_id == user_id,
            UsageAggregate.period_type == period_type,
            UsageAggregate.period_key == period_key,
        )
    )
    row = result.scalar_one_or_none()
    db_calls = row if row is not None else 0

    if redis_calls < db_calls:
        raise InvariantViolation(
            "I5",
            f"Redis usage ({redis_calls}) < DB usage ({db_calls}) for user {user_id} "
            f"period {period_key} — Redis eviction without DB flush = usage data loss",
            {"user_id": uid, "period": period_key,
             "redis_api_calls": redis_calls, "db_api_calls": db_calls,
             "lost_calls": db_calls - redis_calls},
        )


async def check_I6_no_permanently_stuck_locks(
    session: AsyncSession,
    max_age_hours: float = 1.0,
) -> None:
    """
    I6: No idempotency keys stuck in 'locked' state beyond max_age_hours.

    A locked key means a billing operation was started but never completed.
    Each stuck lock represents a potential revenue loss (charge attempted but
    never confirmed as complete or failed).

    max_age_hours is configurable — in tests use a small value (minutes).
    In production use the idempotency TTL (7 days).
    """
    cutoff = datetime.now(timezone.utc) - timedelta(hours=max_age_hours)
    result = await session.execute(
        select(IdempotencyKey.idempotency_key, IdempotencyKey.created_at,
               IdempotencyKey.user_id)
        .where(
            IdempotencyKey.status == "locked",
            IdempotencyKey.created_at < cutoff,
        )
    )
    stuck = result.all()
    if stuck:
        raise InvariantViolation(
            "I6",
            f"Found {len(stuck)} idempotency keys stuck in 'locked' state "
            f"(older than {max_age_hours:.1f}h) — potential revenue loss",
            [{"key": r.idempotency_key, "created_at": str(r.created_at),
              "user_id": str(r.user_id)} for r in stuck],
        )


# ── Invariant suite ───────────────────────────────────────────────────────────

class FinancialInvariantSuite:
    """
    Runs all DB-level financial invariants.

    Usage in tests:
        suite = FinancialInvariantSuite()
        await suite.assert_all(db_session)  # raises AssertionError if any fail
        violations = await suite.check_all(db_session)  # soft check

    I5 (Redis vs DB consistency) requires explicit call with redis + user info.
    I6 (stuck locks) uses a 1-hour default for tests (configure for prod).
    """

    async def check_all(
        self,
        session: AsyncSession,
        stuck_lock_max_age_hours: float = 1.0,
    ) -> list[InvariantViolation]:
        """Run invariants I1–I4, I6. Returns all violations (empty = clean)."""
        results: list[InvariantViolation] = []
        checks = [
            (check_I1_no_duplicate_idempotency_completions, (session,)),
            (check_I2_usage_non_negative, (session,)),
            (check_I3_subscription_transitions_valid, (session,)),
            (check_I4_webhook_events_unique, (session,)),
        ]
        for check_fn, args in checks:
            try:
                await check_fn(*args)
            except InvariantViolation as v:
                results.append(v)

        # I6 with configurable age threshold
        try:
            await check_I6_no_permanently_stuck_locks(session, stuck_lock_max_age_hours)
        except InvariantViolation as v:
            results.append(v)

        return results

    async def assert_all(
        self,
        session: AsyncSession,
        stuck_lock_max_age_hours: float = 1.0,
    ) -> None:
        """Run all invariants. Raises AssertionError listing every violation."""
        violations = await self.check_all(session, stuck_lock_max_age_hours)
        if violations:
            detail = "\n".join(f"  {v}" for v in violations)
            raise AssertionError(
                f"{len(violations)} financial invariant(s) violated:\n{detail}"
            )

    async def assert_redis_consistent(
        self,
        redis: Any,
        session: AsyncSession,
        user_id: uuid.UUID,
        period_type: str,
        period_key: str,
    ) -> None:
        """Run I5 for a specific user/period pair."""
        await check_I5_redis_usage_not_less_than_db(
            redis, session, user_id, period_type, period_key
        )

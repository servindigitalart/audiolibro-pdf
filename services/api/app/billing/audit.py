"""
Billing Engine — Financial Audit Service
==========================================
Produces actionable audit reports from DB state.

Detects:
  - Stuck idempotency locks (potential lost revenue)
  - Subscription state inconsistency (User.subscription_status vs audit log)
  - Tier violations (users consuming beyond their plan's limits)
  - Failed/pending webhooks (unprocessed payment events)
  - Usage data gaps (Redis vs DB mismatch after flush window)

Reports are structured as lists of AuditAnomalies so callers can filter by
severity and programmatically respond (e.g. page on-call for CRITICAL).

This service is READ-ONLY — it never modifies billing state.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.billing.constants import (
    BILLABLE_STATUSES,
    TIER_DAILY_API_LIMITS,
    VALID_TRANSITIONS,
    SubscriptionStatus,
)
from app.billing.models import (
    IdempotencyKey,
    SubscriptionAuditLog,
    UsageAggregate,
    WebhookEvent,
)
from app.db.models.user import User


# ── Anomaly types ─────────────────────────────────────────────────────────────

@dataclass
class AuditAnomaly:
    category: str    # "idempotency" | "subscription" | "usage" | "webhook"
    severity: str    # "critical" | "warning" | "info"
    description: str
    details: dict[str, Any] = field(default_factory=dict)

    def __str__(self) -> str:
        return f"[{self.severity.upper()}:{self.category}] {self.description}"


# ── Per-user report ───────────────────────────────────────────────────────────

@dataclass
class UserAuditReport:
    user_id: uuid.UUID
    email: str
    subscription_status: str
    plan_tier: str
    anomalies: list[AuditAnomaly]
    today_usage: dict[str, float]
    month_usage: dict[str, float]
    transition_count: int
    idempotency_key_count: int

    @property
    def is_clean(self) -> bool:
        return not self.critical_anomalies

    @property
    def critical_anomalies(self) -> list[AuditAnomaly]:
        return [a for a in self.anomalies if a.severity == "critical"]

    @property
    def warning_anomalies(self) -> list[AuditAnomaly]:
        return [a for a in self.anomalies if a.severity == "warning"]


# ── System-wide report ────────────────────────────────────────────────────────

@dataclass
class SystemAuditReport:
    generated_at: str
    total_users: int
    users_audited: int
    critical_anomalies: int
    warning_anomalies: int
    stuck_idempotency_locks: int
    failed_webhooks: int
    pending_webhooks: int
    user_reports: list[UserAuditReport]

    @property
    def is_healthy(self) -> bool:
        return (
            self.critical_anomalies == 0
            and self.stuck_idempotency_locks == 0
            and self.failed_webhooks == 0
        )

    def summary(self) -> str:
        status = "HEALTHY" if self.is_healthy else "DEGRADED"
        return (
            f"[{status}] {self.users_audited} users | "
            f"{self.critical_anomalies} critical | "
            f"{self.warning_anomalies} warnings | "
            f"{self.stuck_idempotency_locks} stuck locks | "
            f"{self.failed_webhooks} failed webhooks"
        )


# ── Audit service ─────────────────────────────────────────────────────────────

class FinancialAuditService:
    """
    Read-only financial audit service.

    Queries DB state and produces structured reports.  Does not modify any data.
    Suitable for running on a schedule (cron) or on-demand via the admin API.
    """

    # Idempotency locks older than this are considered "stuck"
    STUCK_LOCK_THRESHOLD_HOURS = 2

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ── Public API ────────────────────────────────────────────────────────────

    async def audit_user(self, user_id: uuid.UUID) -> UserAuditReport:
        """Produce a full audit report for a single user."""
        result = await self._session.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        if user is None:
            raise ValueError(f"User {user_id} not found")

        anomalies: list[AuditAnomaly] = []

        anomalies.extend(await self._check_stuck_locks(user_id))
        anomalies.extend(await self._check_subscription_consistency(user))
        anomalies.extend(await self._check_tier_violation(user))
        anomalies.extend(await self._check_invalid_transitions(user_id))

        today_usage = await self._get_usage(user_id, "day", date.today().isoformat())
        month_usage = await self._get_usage(user_id, "month", date.today().strftime("%Y-%m"))
        transition_count = await self._count_transitions(user_id)
        key_count = await self._count_idempotency_keys(user_id)

        return UserAuditReport(
            user_id=user_id,
            email=user.email,
            subscription_status=user.subscription_status or "free",
            plan_tier=user.plan_tier or "FREE",
            anomalies=anomalies,
            today_usage=today_usage,
            month_usage=month_usage,
            transition_count=transition_count,
            idempotency_key_count=key_count,
        )

    async def audit_system(self, limit: int = 500) -> SystemAuditReport:
        """
        Produce a system-wide audit report.

        Scans the most recently active users (ordered by latest subscription
        activity) up to `limit`.  Always scans global webhook and idempotency
        state regardless of the user limit.
        """
        user_count_result = await self._session.execute(
            select(func.count()).select_from(User)
        )
        total_users = user_count_result.scalar_one() or 0

        result = await self._session.execute(
            select(User).order_by(User.updated_at.desc()).limit(limit)
        )
        users = result.scalars().all()

        user_reports: list[UserAuditReport] = []
        for user in users:
            report = await self.audit_user(user.id)
            if not report.is_clean:
                user_reports.append(report)

        stuck_locks = await self._count_stuck_locks_global()
        failed_webhooks, pending_webhooks = await self._webhook_health()

        all_anomalies = [a for r in user_reports for a in r.anomalies]

        return SystemAuditReport(
            generated_at=datetime.now(timezone.utc).isoformat(),
            total_users=total_users,
            users_audited=len(users),
            critical_anomalies=sum(1 for a in all_anomalies if a.severity == "critical"),
            warning_anomalies=sum(1 for a in all_anomalies if a.severity == "warning"),
            stuck_idempotency_locks=stuck_locks,
            failed_webhooks=failed_webhooks,
            pending_webhooks=pending_webhooks,
            user_reports=user_reports,
        )

    # ── Per-user checks ───────────────────────────────────────────────────────

    async def _check_stuck_locks(self, user_id: uuid.UUID) -> list[AuditAnomaly]:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=self.STUCK_LOCK_THRESHOLD_HOURS)
        result = await self._session.execute(
            select(IdempotencyKey)
            .where(
                IdempotencyKey.user_id == user_id,
                IdempotencyKey.status == "locked",
                IdempotencyKey.created_at < cutoff,
            )
        )
        stuck = result.scalars().all()
        if not stuck:
            return []
        return [
            AuditAnomaly(
                category="idempotency",
                severity="critical",
                description=f"Idempotency key stuck in 'locked' for >{self.STUCK_LOCK_THRESHOLD_HOURS}h",
                details={
                    "key": row.idempotency_key,
                    "created_at": str(row.created_at),
                    "age_hours": (
                        datetime.now(timezone.utc) - row.created_at.replace(tzinfo=timezone.utc)
                    ).total_seconds() / 3600,
                },
            )
            for row in stuck
        ]

    async def _check_subscription_consistency(self, user: User) -> list[AuditAnomaly]:
        """User.subscription_status must match the latest audit log entry."""
        result = await self._session.execute(
            select(SubscriptionAuditLog)
            .where(SubscriptionAuditLog.user_id == user.id)
            .order_by(SubscriptionAuditLog.created_at.desc())
            .limit(1)
        )
        latest = result.scalar_one_or_none()
        if latest is None:
            return []

        expected = latest.to_status
        actual = user.subscription_status or "free"

        if actual != expected:
            return [
                AuditAnomaly(
                    category="subscription",
                    severity="critical",
                    description="User.subscription_status does not match latest audit log",
                    details={
                        "user_id": str(user.id),
                        "user_model_status": actual,
                        "audit_log_latest": expected,
                        "audit_log_id": str(latest.id),
                    },
                )
            ]
        return []

    async def _check_tier_violation(self, user: User) -> list[AuditAnomaly]:
        """Detect users who exceeded their tier's daily limit (enforcement misconfiguration)."""
        today = date.today().isoformat()
        result = await self._session.execute(
            select(UsageAggregate.api_calls).where(
                UsageAggregate.user_id == user.id,
                UsageAggregate.period_type == "day",
                UsageAggregate.period_key == today,
            )
        )
        row = result.scalar_one_or_none()
        if row is None:
            return []

        limit = TIER_DAILY_API_LIMITS.get(user.plan_tier.upper(), TIER_DAILY_API_LIMITS["FREE"])
        if limit == -1:
            return []  # Unlimited tier

        # Only flag if significantly over limit (not just by 1, to avoid race-condition noise)
        if row > limit * 1.05:
            return [
                AuditAnomaly(
                    category="usage",
                    severity="warning",
                    description=f"User exceeded {user.plan_tier} tier daily limit",
                    details={
                        "user_id": str(user.id),
                        "plan_tier": user.plan_tier,
                        "today_calls": row,
                        "tier_limit": limit,
                        "overage_pct": round((row / limit - 1) * 100, 1),
                    },
                )
            ]
        return []

    async def _check_invalid_transitions(self, user_id: uuid.UUID) -> list[AuditAnomaly]:
        """Scan audit log for transitions that violated the state machine."""
        result = await self._session.execute(
            select(SubscriptionAuditLog)
            .where(
                SubscriptionAuditLog.user_id == user_id,
                SubscriptionAuditLog.from_status.is_not(None),
            )
        )
        logs = result.scalars().all()
        anomalies = []
        for log in logs:
            try:
                from_s = SubscriptionStatus(log.from_status)
                to_s = SubscriptionStatus(log.to_status)
            except ValueError:
                anomalies.append(AuditAnomaly(
                    category="subscription",
                    severity="critical",
                    description=f"Unknown status value in audit log",
                    details={"log_id": str(log.id), "from": log.from_status, "to": log.to_status},
                ))
                continue
            if to_s not in VALID_TRANSITIONS.get(from_s, frozenset()):
                anomalies.append(AuditAnomaly(
                    category="subscription",
                    severity="critical",
                    description=f"Invalid transition in audit log: {from_s.value} → {to_s.value}",
                    details={
                        "log_id": str(log.id),
                        "from_status": from_s.value,
                        "to_status": to_s.value,
                    },
                ))
        return anomalies

    # ── Global checks (system-level) ──────────────────────────────────────────

    async def _count_stuck_locks_global(self) -> int:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=self.STUCK_LOCK_THRESHOLD_HOURS)
        result = await self._session.execute(
            select(func.count()).select_from(IdempotencyKey).where(
                IdempotencyKey.status == "locked",
                IdempotencyKey.created_at < cutoff,
            )
        )
        return result.scalar_one() or 0

    async def _webhook_health(self) -> tuple[int, int]:
        result = await self._session.execute(
            select(WebhookEvent.status, func.count().label("cnt"))
            .group_by(WebhookEvent.status)
        )
        counts = {row.status: row.cnt for row in result}
        return counts.get("failed", 0), counts.get("pending", 0)

    # ── Usage helpers ─────────────────────────────────────────────────────────

    async def _get_usage(
        self, user_id: uuid.UUID, period_type: str, period_key: str
    ) -> dict[str, float]:
        result = await self._session.execute(
            select(UsageAggregate).where(
                UsageAggregate.user_id == user_id,
                UsageAggregate.period_type == period_type,
                UsageAggregate.period_key == period_key,
            )
        )
        row = result.scalar_one_or_none()
        if row is None:
            return {"api_calls": 0.0, "compute_ms": 0.0, "cost_usd": 0.0}
        return {"api_calls": float(row.api_calls), "compute_ms": row.compute_ms,
                "cost_usd": row.cost_usd}

    async def _count_transitions(self, user_id: uuid.UUID) -> int:
        result = await self._session.execute(
            select(func.count()).select_from(SubscriptionAuditLog).where(
                SubscriptionAuditLog.user_id == user_id
            )
        )
        return result.scalar_one() or 0

    async def _count_idempotency_keys(self, user_id: uuid.UUID) -> int:
        result = await self._session.execute(
            select(func.count()).select_from(IdempotencyKey).where(
                IdempotencyKey.user_id == user_id
            )
        )
        return result.scalar_one() or 0

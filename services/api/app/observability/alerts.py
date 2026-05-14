"""
Production Observability — Alert Engine
========================================
Detects anomalies in billing and API health by querying DB state.
Fires structured alerts to registered handlers (log, Slack, PagerDuty, etc.).

Alert types:
  PAYMENT_FAILURE_SPIKE  — invoice.payment_failed rate exceeds threshold
  WEBHOOK_FAILURE_RATE   — webhook processing failure rate exceeds threshold
  LATENCY_BUDGET_BREACH  — p95 API latency exceeds SLO budget
  ERROR_RATE_SPIKE       — HTTP 5xx rate exceeds threshold
  REVENUE_ANOMALY        — sudden MRR drop or zero revenue window
  IDEMPOTENCY_STUCK      — locked idempotency keys older than threshold

Design:
  - All checks are async and read-only
  - Handlers are registered callbacks — swap for Slack/PD/email in production
  - Engine can run standalone or be embedded in a periodic background task
  - Thresholds are configurable (defaults are opinionated production values)
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Awaitable, Callable, Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


# ── Alert types ───────────────────────────────────────────────────────────────

class AlertSeverity(str, Enum):
    INFO     = "info"
    WARNING  = "warning"
    CRITICAL = "critical"


class AlertType(str, Enum):
    PAYMENT_FAILURE_SPIKE  = "payment_failure_spike"
    WEBHOOK_FAILURE_RATE   = "webhook_failure_rate"
    LATENCY_BUDGET_BREACH  = "latency_budget_breach"
    ERROR_RATE_SPIKE       = "error_rate_spike"
    REVENUE_ANOMALY        = "revenue_anomaly"
    IDEMPOTENCY_STUCK      = "idempotency_stuck"
    RECONCILIATION_DRIFT   = "reconciliation_drift"


@dataclass
class Alert:
    type: AlertType
    severity: AlertSeverity
    message: str
    details: dict
    fired_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def as_dict(self) -> dict:
        return {
            "type": self.type.value,
            "severity": self.severity.value,
            "message": self.message,
            "details": self.details,
            "fired_at": self.fired_at,
        }

    def __str__(self) -> str:
        return f"[{self.severity.upper()}:{self.type}] {self.message}"


AlertHandler = Callable[[Alert], Awaitable[None]]


# ── Engine ────────────────────────────────────────────────────────────────────

class AlertEngine:
    """
    Evaluates billing health checks and fires structured alerts to handlers.

    Usage:
        engine = AlertEngine()
        engine.register_handler(log_handler)
        engine.register_handler(slack_handler)

        alerts = await engine.run_all_checks(session)
        # → list[Alert] for any threshold that was breached

    Handlers receive every Alert as it fires.  Handlers that raise are
    silently skipped so a broken handler never suppresses other alerts.
    """

    # Default thresholds (override via constructor)
    DEFAULT_PAYMENT_FAILURE_RATE   = 0.10   # 10% of recent invoices failed
    DEFAULT_WEBHOOK_FAILURE_RATE   = 0.05   # 5% of recent webhooks failed
    DEFAULT_STUCK_LOCK_AGE_HOURS   = 2.0    # idempotency lock stuck > 2h
    DEFAULT_RECONCILIATION_DRIFT   = 0.02   # > 2% of reconciled users had drift

    def __init__(
        self,
        payment_failure_threshold: float = DEFAULT_PAYMENT_FAILURE_RATE,
        webhook_failure_threshold: float = DEFAULT_WEBHOOK_FAILURE_RATE,
        stuck_lock_age_hours: float = DEFAULT_STUCK_LOCK_AGE_HOURS,
        reconciliation_drift_threshold: float = DEFAULT_RECONCILIATION_DRIFT,
    ) -> None:
        self._payment_threshold = payment_failure_threshold
        self._webhook_threshold = webhook_failure_threshold
        self._stuck_hours = stuck_lock_age_hours
        self._recon_threshold = reconciliation_drift_threshold
        self._handlers: list[AlertHandler] = []
        self._fired: list[Alert] = []

    # ── Handler registration ──────────────────────────────────────────────────

    def register_handler(self, handler: AlertHandler) -> None:
        """Register a handler coroutine.  Called for every fired alert."""
        self._handlers.append(handler)

    def last_alerts(self) -> list[Alert]:
        """Return alerts fired during the last run_all_checks() call."""
        return list(self._fired)

    # ── Check suite ───────────────────────────────────────────────────────────

    async def run_all_checks(self, session: AsyncSession) -> list[Alert]:
        """
        Run all built-in health checks.
        Returns the list of alerts fired (empty = healthy).
        """
        self._fired.clear()
        await self._check_payment_failures(session)
        await self._check_webhook_failures(session)
        await self._check_stuck_idempotency_locks(session)
        await self._check_revenue_window(session)
        return list(self._fired)

    # ── Individual checks ─────────────────────────────────────────────────────

    async def _check_payment_failures(self, session: AsyncSession) -> None:
        """Alert if recent payment failure rate exceeds threshold."""
        from app.billing.models import WebhookEvent

        cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
        result = await session.execute(
            select(WebhookEvent.status, func.count().label("cnt"))
            .where(
                WebhookEvent.event_type == "invoice.payment_failed",
                WebhookEvent.created_at >= cutoff,
            )
            .group_by(WebhookEvent.status)
        )
        counts = {row.status: row.cnt for row in result}
        failed = counts.get("processed", 0)  # payment_failed events that were processed
        total_invoices_result = await session.execute(
            select(func.count()).select_from(WebhookEvent).where(
                WebhookEvent.event_type.in_(["invoice.paid", "invoice.payment_failed"]),
                WebhookEvent.created_at >= cutoff,
            )
        )
        total = total_invoices_result.scalar_one() or 0
        if total < 5:
            return  # Not enough data to alert
        rate = failed / total
        if rate >= self._payment_threshold:
            await self._fire(
                AlertType.PAYMENT_FAILURE_SPIKE,
                AlertSeverity.CRITICAL if rate >= 0.25 else AlertSeverity.WARNING,
                f"Payment failure rate {rate:.1%} exceeds threshold {self._payment_threshold:.1%}",
                {"failed": failed, "total": total, "rate": rate, "window_hours": 24},
            )

    async def _check_webhook_failures(self, session: AsyncSession) -> None:
        """Alert if webhook processing failure rate exceeds threshold."""
        from app.billing.models import WebhookEvent

        cutoff = datetime.now(timezone.utc) - timedelta(hours=1)
        result = await session.execute(
            select(WebhookEvent.status, func.count().label("cnt"))
            .where(WebhookEvent.created_at >= cutoff)
            .group_by(WebhookEvent.status)
        )
        counts = {row.status: row.cnt for row in result}
        failed = counts.get("failed", 0)
        total = sum(counts.values())

        if total < 3:
            return
        rate = failed / total
        if rate >= self._webhook_threshold:
            await self._fire(
                AlertType.WEBHOOK_FAILURE_RATE,
                AlertSeverity.CRITICAL if rate >= 0.2 else AlertSeverity.WARNING,
                f"Webhook failure rate {rate:.1%} in last hour (threshold {self._webhook_threshold:.1%})",
                {"failed": failed, "total": total, "rate": rate, "counts": counts},
            )

    async def _check_stuck_idempotency_locks(self, session: AsyncSession) -> None:
        """Alert on idempotency keys stuck in 'locked' state beyond threshold."""
        from app.billing.models import IdempotencyKey

        cutoff = datetime.now(timezone.utc) - timedelta(hours=self._stuck_hours)
        result = await session.execute(
            select(func.count()).select_from(IdempotencyKey).where(
                IdempotencyKey.status == "locked",
                IdempotencyKey.created_at < cutoff,
            )
        )
        stuck = result.scalar_one() or 0
        if stuck > 0:
            await self._fire(
                AlertType.IDEMPOTENCY_STUCK,
                AlertSeverity.CRITICAL,
                f"{stuck} idempotency key(s) stuck in 'locked' state for >{self._stuck_hours:.0f}h",
                {"stuck_count": stuck, "age_threshold_hours": self._stuck_hours},
            )

    async def _check_revenue_window(self, session: AsyncSession) -> None:
        """Alert if there have been zero successful payments in the last 24h (anomaly)."""
        from app.billing.models import WebhookEvent

        cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
        result = await session.execute(
            select(func.count()).select_from(WebhookEvent).where(
                WebhookEvent.event_type == "invoice.paid",
                WebhookEvent.status == "processed",
                WebhookEvent.created_at >= cutoff,
            )
        )
        paid_count = result.scalar_one() or 0

        # Only alert if the system has been running long enough to have data
        total_result = await session.execute(
            select(func.count()).select_from(WebhookEvent)
        )
        total_ever = total_result.scalar_one() or 0

        if total_ever >= 10 and paid_count == 0:
            await self._fire(
                AlertType.REVENUE_ANOMALY,
                AlertSeverity.WARNING,
                "Zero successful invoice payments in the last 24h (possible revenue gap)",
                {"paid_last_24h": paid_count, "total_events_ever": total_ever},
            )

    # ── Manual alert fire ─────────────────────────────────────────────────────

    async def fire_reconciliation_alert(self, drift_rate: float, synced: int, total: int) -> None:
        """Fire when reconciliation finds a high drift rate."""
        if drift_rate >= self._recon_threshold and total >= 5:
            await self._fire(
                AlertType.RECONCILIATION_DRIFT,
                AlertSeverity.WARNING,
                f"Reconciliation drift {drift_rate:.1%}: {synced}/{total} users needed state correction",
                {"drift_rate": drift_rate, "synced": synced, "total": total},
            )

    async def fire_latency_breach(self, endpoint: str, p95_ms: float, budget_ms: float) -> None:
        """Fire when a latency SLO is breached (call from monitoring middleware)."""
        if p95_ms > budget_ms:
            await self._fire(
                AlertType.LATENCY_BUDGET_BREACH,
                AlertSeverity.WARNING,
                f"p95 latency {p95_ms:.0f}ms exceeds {budget_ms:.0f}ms budget on {endpoint}",
                {"endpoint": endpoint, "p95_ms": p95_ms, "budget_ms": budget_ms},
            )

    # ── Internal ──────────────────────────────────────────────────────────────

    async def _fire(
        self,
        alert_type: AlertType,
        severity: AlertSeverity,
        message: str,
        details: dict,
    ) -> None:
        alert = Alert(type=alert_type, severity=severity, message=message, details=details)
        self._fired.append(alert)
        logger.warning(
            "billing_alert",
            extra={
                "alert_type": alert_type.value,
                "severity": severity.value,
                "alert_message": message,
                "details": details,
            },
        )
        for handler in self._handlers:
            try:
                await handler(alert)
            except Exception as exc:
                logger.error(f"Alert handler failed: {exc}", exc_info=True)


# ── Built-in handlers ─────────────────────────────────────────────────────────

async def log_alert_handler(alert: Alert) -> None:
    """Default handler: structured log at WARNING/ERROR level."""
    level = logging.CRITICAL if alert.severity == AlertSeverity.CRITICAL else logging.WARNING
    # Exclude "message" — it's a reserved LogRecord attribute and cannot be in extra
    extra = {k: v for k, v in alert.as_dict().items() if k != "message"}
    logger.log(level, str(alert), extra=extra)


async def noop_alert_handler(alert: Alert) -> None:
    """No-op handler for tests (suppresses all output)."""

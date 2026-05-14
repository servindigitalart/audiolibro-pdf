"""
AlertEngine Tests
==================
Tests the production observability alert system with real DB sessions.

Scenarios:
  - No alerts when DB is empty (no false positives)
  - Handler registration and invocation
  - Payment failure spike detection (threshold + severity)
  - Webhook failure rate detection
  - Stuck idempotency key detection
  - Revenue anomaly (zero payments in 24h after system has data)
  - Reconciliation drift alert
  - Latency SLO breach alert
  - Multiple handlers all invoked
  - Broken handler does not suppress other alerts
  - run_all_checks returns empty list when healthy
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone

from app.billing.models import IdempotencyKey, WebhookEvent
from app.observability.alerts import (
    Alert,
    AlertEngine,
    AlertSeverity,
    AlertType,
    log_alert_handler,
    noop_alert_handler,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _insert_webhook_event(
    db_session,
    *,
    event_type: str,
    status: str = "processed",
    created_at: datetime | None = None,
) -> WebhookEvent:
    event = WebhookEvent(
        stripe_event_id=f"evt_{uuid.uuid4().hex}",
        event_type=event_type,
        payload=json.dumps({"id": "evt_x", "type": event_type, "data": {}}),
        status=status,
        created_at=created_at or datetime.now(timezone.utc),
    )
    db_session.add(event)
    await db_session.flush()
    return event


async def _insert_idempotency_key(
    db_session,
    *,
    status: str = "locked",
    created_at: datetime | None = None,
) -> IdempotencyKey:
    key = IdempotencyKey(
        idempotency_key=f"stuck_{uuid.uuid4().hex}",
        user_id=None,
        status=status,
        expires_at=datetime.now(timezone.utc) + timedelta(days=1),
        created_at=created_at or datetime.now(timezone.utc),
    )
    db_session.add(key)
    await db_session.flush()
    return key


# ── Healthy (no alerts) ───────────────────────────────────────────────────────

async def test_empty_db_no_alerts(db_session):
    engine = AlertEngine()
    engine.register_handler(noop_alert_handler)
    alerts = await engine.run_all_checks(db_session)
    assert alerts == []


async def test_run_all_checks_returns_list(db_session):
    engine = AlertEngine()
    result = await engine.run_all_checks(db_session)
    assert isinstance(result, list)


# ── Handler registration ──────────────────────────────────────────────────────

async def test_handler_is_called_when_alert_fires(db_session):
    received: list[Alert] = []

    async def capture(alert: Alert) -> None:
        received.append(alert)

    engine = AlertEngine(stuck_lock_age_hours=0.0)  # Threshold = 0h → always triggers
    engine.register_handler(capture)

    old = datetime.now(timezone.utc) - timedelta(hours=3)
    await _insert_idempotency_key(db_session, status="locked", created_at=old)

    await engine.run_all_checks(db_session)
    assert len(received) >= 1


async def test_multiple_handlers_all_invoked(db_session):
    calls_a: list[Alert] = []
    calls_b: list[Alert] = []

    async def handler_a(a: Alert) -> None:
        calls_a.append(a)

    async def handler_b(a: Alert) -> None:
        calls_b.append(a)

    engine = AlertEngine(stuck_lock_age_hours=0.0)
    engine.register_handler(handler_a)
    engine.register_handler(handler_b)

    old = datetime.now(timezone.utc) - timedelta(hours=3)
    await _insert_idempotency_key(db_session, status="locked", created_at=old)

    await engine.run_all_checks(db_session)

    assert len(calls_a) >= 1
    assert len(calls_b) >= 1


async def test_broken_handler_does_not_suppress_other_alerts(db_session):
    received: list[Alert] = []

    async def broken_handler(_a: Alert) -> None:
        raise RuntimeError("handler failure")

    async def good_handler(a: Alert) -> None:
        received.append(a)

    engine = AlertEngine(stuck_lock_age_hours=0.0)
    engine.register_handler(broken_handler)
    engine.register_handler(good_handler)

    old = datetime.now(timezone.utc) - timedelta(hours=3)
    await _insert_idempotency_key(db_session, status="locked", created_at=old)

    await engine.run_all_checks(db_session)

    assert len(received) >= 1  # good_handler still received the alert


# ── last_alerts() ─────────────────────────────────────────────────────────────

async def test_last_alerts_reflects_most_recent_run(db_session):
    engine = AlertEngine(stuck_lock_age_hours=0.0)
    engine.register_handler(noop_alert_handler)

    old = datetime.now(timezone.utc) - timedelta(hours=3)
    await _insert_idempotency_key(db_session, status="locked", created_at=old)

    alerts = await engine.run_all_checks(db_session)
    assert engine.last_alerts() == alerts


async def test_last_alerts_clears_between_runs(db_session):
    engine = AlertEngine(stuck_lock_age_hours=0.0)
    engine.register_handler(noop_alert_handler)

    old = datetime.now(timezone.utc) - timedelta(hours=3)
    await _insert_idempotency_key(db_session, status="locked", created_at=old)

    await engine.run_all_checks(db_session)
    first_count = len(engine.last_alerts())

    await engine.run_all_checks(db_session)
    second_count = len(engine.last_alerts())

    # Counts are equal — not accumulating across runs
    assert first_count == second_count


# ── Payment failure spike ─────────────────────────────────────────────────────

async def test_payment_failure_spike_fires_above_threshold(db_session):
    # 6 invoice.payment_failed + 4 invoice.paid → 60% failure rate (threshold 10%)
    now = datetime.now(timezone.utc)
    for _ in range(6):
        await _insert_webhook_event(db_session, event_type="invoice.payment_failed", created_at=now)
    for _ in range(4):
        await _insert_webhook_event(db_session, event_type="invoice.paid", created_at=now)

    engine = AlertEngine(payment_failure_threshold=0.10)
    engine.register_handler(noop_alert_handler)
    alerts = await engine.run_all_checks(db_session)

    payment_alerts = [a for a in alerts if a.type == AlertType.PAYMENT_FAILURE_SPIKE]
    assert len(payment_alerts) == 1


async def test_payment_failure_spike_critical_above_25_percent(db_session):
    now = datetime.now(timezone.utc)
    for _ in range(8):
        await _insert_webhook_event(db_session, event_type="invoice.payment_failed", created_at=now)
    for _ in range(2):
        await _insert_webhook_event(db_session, event_type="invoice.paid", created_at=now)

    engine = AlertEngine(payment_failure_threshold=0.10)
    engine.register_handler(noop_alert_handler)
    alerts = await engine.run_all_checks(db_session)

    spike = next(a for a in alerts if a.type == AlertType.PAYMENT_FAILURE_SPIKE)
    assert spike.severity == AlertSeverity.CRITICAL


async def test_payment_failure_spike_not_fired_below_threshold(db_session):
    # 0 failures out of 10 invoices → 0% failure rate, below 10% threshold
    now = datetime.now(timezone.utc)
    for _ in range(10):
        await _insert_webhook_event(db_session, event_type="invoice.paid", created_at=now)

    engine = AlertEngine(payment_failure_threshold=0.10)
    engine.register_handler(noop_alert_handler)
    alerts = await engine.run_all_checks(db_session)

    payment_alerts = [a for a in alerts if a.type == AlertType.PAYMENT_FAILURE_SPIKE]
    assert len(payment_alerts) == 0


async def test_payment_failure_minimum_sample_size_not_met(db_session):
    # Only 4 total events — below minimum sample of 5
    now = datetime.now(timezone.utc)
    for _ in range(3):
        await _insert_webhook_event(db_session, event_type="invoice.payment_failed", created_at=now)
    await _insert_webhook_event(db_session, event_type="invoice.paid", created_at=now)

    engine = AlertEngine(payment_failure_threshold=0.10)
    engine.register_handler(noop_alert_handler)
    alerts = await engine.run_all_checks(db_session)

    payment_alerts = [a for a in alerts if a.type == AlertType.PAYMENT_FAILURE_SPIKE]
    assert len(payment_alerts) == 0


# ── Webhook failure rate ──────────────────────────────────────────────────────

async def test_webhook_failure_rate_fires_above_threshold(db_session):
    now = datetime.now(timezone.utc)
    for _ in range(4):
        await _insert_webhook_event(db_session, event_type="invoice.paid", status="failed", created_at=now)
    for _ in range(6):
        await _insert_webhook_event(db_session, event_type="invoice.paid", status="processed", created_at=now)

    engine = AlertEngine(webhook_failure_threshold=0.05)
    engine.register_handler(noop_alert_handler)
    alerts = await engine.run_all_checks(db_session)

    wh_alerts = [a for a in alerts if a.type == AlertType.WEBHOOK_FAILURE_RATE]
    assert len(wh_alerts) == 1


async def test_webhook_failure_rate_skips_old_events(db_session):
    # Old events (> 1h ago) should not be counted
    old = datetime.now(timezone.utc) - timedelta(hours=2)
    for _ in range(10):
        await _insert_webhook_event(db_session, event_type="invoice.paid", status="failed", created_at=old)

    engine = AlertEngine(webhook_failure_threshold=0.05)
    engine.register_handler(noop_alert_handler)
    alerts = await engine.run_all_checks(db_session)

    wh_alerts = [a for a in alerts if a.type == AlertType.WEBHOOK_FAILURE_RATE]
    assert len(wh_alerts) == 0


# ── Stuck idempotency keys ────────────────────────────────────────────────────

async def test_stuck_idempotency_key_fires_alert(db_session):
    old = datetime.now(timezone.utc) - timedelta(hours=3)
    await _insert_idempotency_key(db_session, status="locked", created_at=old)

    engine = AlertEngine(stuck_lock_age_hours=2.0)
    engine.register_handler(noop_alert_handler)
    alerts = await engine.run_all_checks(db_session)

    stuck_alerts = [a for a in alerts if a.type == AlertType.IDEMPOTENCY_STUCK]
    assert len(stuck_alerts) == 1
    assert stuck_alerts[0].severity == AlertSeverity.CRITICAL


async def test_recent_locked_key_does_not_fire(db_session):
    now = datetime.now(timezone.utc)
    await _insert_idempotency_key(db_session, status="locked", created_at=now)

    engine = AlertEngine(stuck_lock_age_hours=2.0)
    engine.register_handler(noop_alert_handler)
    alerts = await engine.run_all_checks(db_session)

    stuck_alerts = [a for a in alerts if a.type == AlertType.IDEMPOTENCY_STUCK]
    assert len(stuck_alerts) == 0


async def test_completed_key_does_not_trigger_stuck_alert(db_session):
    old = datetime.now(timezone.utc) - timedelta(hours=3)
    await _insert_idempotency_key(db_session, status="complete", created_at=old)

    engine = AlertEngine(stuck_lock_age_hours=2.0)
    engine.register_handler(noop_alert_handler)
    alerts = await engine.run_all_checks(db_session)

    stuck_alerts = [a for a in alerts if a.type == AlertType.IDEMPOTENCY_STUCK]
    assert len(stuck_alerts) == 0


# ── Revenue anomaly ───────────────────────────────────────────────────────────

async def test_zero_payments_fires_revenue_anomaly_when_enough_history(db_session):
    # Insert 10+ total events but none are invoice.paid in last 24h
    old = datetime.now(timezone.utc) - timedelta(hours=48)
    for _ in range(10):
        await _insert_webhook_event(db_session, event_type="invoice.paid", created_at=old)

    engine = AlertEngine()
    engine.register_handler(noop_alert_handler)
    alerts = await engine.run_all_checks(db_session)

    revenue_alerts = [a for a in alerts if a.type == AlertType.REVENUE_ANOMALY]
    assert len(revenue_alerts) == 1


async def test_revenue_anomaly_not_fired_with_recent_payments(db_session):
    now = datetime.now(timezone.utc)
    for _ in range(3):
        await _insert_webhook_event(db_session, event_type="invoice.paid", created_at=now)

    engine = AlertEngine()
    engine.register_handler(noop_alert_handler)
    alerts = await engine.run_all_checks(db_session)

    revenue_alerts = [a for a in alerts if a.type == AlertType.REVENUE_ANOMALY]
    assert len(revenue_alerts) == 0


async def test_revenue_anomaly_not_fired_when_too_little_history(db_session):
    # Only 5 total events ever — not enough to establish baseline
    old = datetime.now(timezone.utc) - timedelta(hours=48)
    for _ in range(5):
        await _insert_webhook_event(db_session, event_type="invoice.paid", created_at=old)

    engine = AlertEngine()
    engine.register_handler(noop_alert_handler)
    alerts = await engine.run_all_checks(db_session)

    revenue_alerts = [a for a in alerts if a.type == AlertType.REVENUE_ANOMALY]
    assert len(revenue_alerts) == 0


# ── Reconciliation drift alert ────────────────────────────────────────────────

async def test_reconciliation_alert_fires_above_threshold():
    received: list[Alert] = []

    async def capture(a: Alert) -> None:
        received.append(a)

    engine = AlertEngine(reconciliation_drift_threshold=0.02)
    engine.register_handler(capture)

    await engine.fire_reconciliation_alert(drift_rate=0.15, synced=15, total=100)

    assert len(received) == 1
    assert received[0].type == AlertType.RECONCILIATION_DRIFT


async def test_reconciliation_alert_not_fired_below_threshold():
    received: list[Alert] = []

    async def capture(a: Alert) -> None:
        received.append(a)

    engine = AlertEngine(reconciliation_drift_threshold=0.02)
    engine.register_handler(capture)

    await engine.fire_reconciliation_alert(drift_rate=0.01, synced=1, total=100)

    assert len(received) == 0


async def test_reconciliation_alert_requires_minimum_sample():
    received: list[Alert] = []

    async def capture(a: Alert) -> None:
        received.append(a)

    engine = AlertEngine(reconciliation_drift_threshold=0.02)
    engine.register_handler(capture)

    # Only 3 users — below minimum of 5
    await engine.fire_reconciliation_alert(drift_rate=0.50, synced=2, total=3)

    assert len(received) == 0


# ── Latency SLO breach ────────────────────────────────────────────────────────

async def test_latency_breach_fires_when_p95_exceeds_budget():
    received: list[Alert] = []

    async def capture(a: Alert) -> None:
        received.append(a)

    engine = AlertEngine()
    engine.register_handler(capture)

    await engine.fire_latency_breach("/api/v1/convert", p95_ms=2500.0, budget_ms=1000.0)

    assert len(received) == 1
    assert received[0].type == AlertType.LATENCY_BUDGET_BREACH


async def test_latency_breach_not_fired_within_budget():
    received: list[Alert] = []

    async def capture(a: Alert) -> None:
        received.append(a)

    engine = AlertEngine()
    engine.register_handler(capture)

    await engine.fire_latency_breach("/api/v1/convert", p95_ms=800.0, budget_ms=1000.0)

    assert len(received) == 0


# ── Alert.as_dict() ───────────────────────────────────────────────────────────

async def test_alert_as_dict_contains_all_fields():
    received: list[Alert] = []

    async def capture(a: Alert) -> None:
        received.append(a)

    engine = AlertEngine(stuck_lock_age_hours=0.0)
    engine.register_handler(capture)

    # Trigger via fire_latency_breach (no DB needed)
    await engine.fire_latency_breach("endpoint", p95_ms=9999.0, budget_ms=100.0)

    alert = received[0]
    d = alert.as_dict()
    assert "type" in d
    assert "severity" in d
    assert "message" in d
    assert "details" in d
    assert "fired_at" in d


# ── noop vs log handlers ──────────────────────────────────────────────────────

async def test_noop_handler_does_not_raise():
    alert = Alert(
        type=AlertType.IDEMPOTENCY_STUCK,
        severity=AlertSeverity.CRITICAL,
        message="test",
        details={},
    )
    await noop_alert_handler(alert)  # Must not raise


async def test_log_alert_handler_does_not_raise():
    alert = Alert(
        type=AlertType.WEBHOOK_FAILURE_RATE,
        severity=AlertSeverity.WARNING,
        message="test warning",
        details={"failed": 2, "total": 10},
    )
    await log_alert_handler(alert)  # Must not raise

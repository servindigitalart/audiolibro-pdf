"""
Billing Engine — Internal API Router
=======================================
Endpoints:
  GET  /internal/billing/metrics              — revenue & usage summary (admin only)
  GET  /internal/billing/metrics/user/{id}    — per-user usage (admin only)
  POST /internal/billing/webhook/replay       — replay a stored webhook event (admin only)
  POST /internal/billing/reconcile/{user_id}  — reconcile one user vs Stripe (admin only)
  POST /internal/billing/reconcile/bulk       — reconcile all Stripe-linked users (admin only)
  GET  /internal/billing/health               — billing health check + alerts (admin only)
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.billing.metrics import BillingMetricsService
from app.billing.webhook import WebhookService
from app.core.config import settings
from app.db.session import get_db
from app.core.auth_dependencies import require_admin

router = APIRouter(prefix="/internal/billing", tags=["internal-billing"])


# ── Metrics ───────────────────────────────────────────────────────────────────

@router.get("/metrics")
async def get_billing_metrics(
    session: AsyncSession = Depends(get_db),
    _admin=Depends(require_admin),
):
    """Revenue and usage summary across all users."""
    svc = BillingMetricsService(session)
    return await svc.get_summary()


@router.get("/metrics/user/{user_id}")
async def get_user_billing_metrics(
    user_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
    _admin=Depends(require_admin),
):
    """Per-user daily and monthly usage."""
    svc = BillingMetricsService(session)
    return await svc.get_user_usage(user_id)


# ── Webhook replay ────────────────────────────────────────────────────────────

@router.post("/webhook/replay")
async def replay_webhook(
    stripe_event_id: str,
    session: AsyncSession = Depends(get_db),
    _admin=Depends(require_admin),
):
    """Replay a stored webhook event (debugging)."""
    svc = WebhookService(session, webhook_secret=settings.stripe_webhook_secret)
    try:
        event = await svc.replay(stripe_event_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return {"status": event.status, "stripe_event_id": event.stripe_event_id}


# ── Reconciliation ────────────────────────────────────────────────────────────

@router.post("/reconcile/{user_id}")
async def reconcile_user(
    user_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
    _admin=Depends(require_admin),
):
    """
    Reconcile a single user's subscription state against Stripe.
    Corrects any drift between local DB and Stripe source-of-truth.
    """
    from sqlalchemy import select
    from app.db.models.user import User
    from app.billing.reconciliation import ReconciliationService
    from app.billing.stripe.factory import get_stripe_provider

    result = await session.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=404, detail=f"User {user_id} not found")

    svc = ReconciliationService(session)
    stripe = get_stripe_provider()
    rec_result = await svc.reconcile_user(user, stripe)
    return {
        "user_id": str(rec_result.user_id),
        "outcome": rec_result.outcome,
        "drift_detected": rec_result.drift_detected,
        "previous_status": rec_result.previous_status,
        "new_status": rec_result.new_status,
        "stripe_subscription_id": rec_result.stripe_subscription_id,
        "stripe_status": rec_result.stripe_status,
        "detail": rec_result.detail,
        "reconciled_at": rec_result.reconciled_at,
    }


@router.post("/reconcile/bulk")
async def reconcile_bulk(
    limit: int = 200,
    session: AsyncSession = Depends(get_db),
    _admin=Depends(require_admin),
):
    """
    Reconcile the most recently active users (up to `limit`) against Stripe.
    Returns a summary report with drift statistics.
    """
    from app.billing.reconciliation import ReconciliationService
    from app.billing.stripe.factory import get_stripe_provider
    from app.observability.alerts import AlertEngine, log_alert_handler

    svc = ReconciliationService(session)
    stripe = get_stripe_provider()
    report = await svc.reconcile_bulk(stripe, limit=limit)

    # Fire alert if drift rate is elevated
    engine = AlertEngine()
    engine.register_handler(log_alert_handler)
    if report.users_checked > 0:
        await engine.fire_reconciliation_alert(
            drift_rate=report.drift_rate,
            synced=report.synced,
            total=report.users_checked,
        )

    return {
        "run_at": report.run_at,
        "total_users": report.total_users,
        "users_checked": report.users_checked,
        "synced": report.synced,
        "errors": report.errors,
        "drift_rate": report.drift_rate,
        "alerts_fired": len(engine.last_alerts()),
    }


# ── Billing health ────────────────────────────────────────────────────────────

@router.get("/health")
async def billing_health(
    session: AsyncSession = Depends(get_db),
    _admin=Depends(require_admin),
):
    """
    Run all billing health checks and return structured alert report.
    Returns HTTP 200 with is_healthy=true when no alerts fire.
    Returns HTTP 200 with is_healthy=false (not 5xx) when alerts exist —
    callers decide whether to page on-call.
    """
    from app.observability.alerts import AlertEngine, noop_alert_handler

    engine = AlertEngine()
    engine.register_handler(noop_alert_handler)
    alerts = await engine.run_all_checks(session)

    critical = [a for a in alerts if a.severity.value == "critical"]
    warnings = [a for a in alerts if a.severity.value == "warning"]

    return {
        "is_healthy": len(critical) == 0,
        "critical_count": len(critical),
        "warning_count": len(warnings),
        "alerts": [a.as_dict() for a in alerts],
    }

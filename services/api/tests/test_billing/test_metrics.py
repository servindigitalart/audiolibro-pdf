"""
Billing Metrics Service Tests
================================
Validates revenue/usage aggregation and the summary endpoint structure.
"""
from __future__ import annotations

import uuid
from datetime import date

import pytest
from sqlalchemy import insert

from app.billing.metrics import BillingMetricsService
from app.billing.models import UsageAggregate, WebhookEvent




async def _insert_usage(db_session, user_id: uuid.UUID, period_type: str, period_key: str,
                         api_calls: int, compute_ms: float, cost_usd: float):
    await db_session.execute(
        insert(UsageAggregate).values(
            id=uuid.uuid4(),
            user_id=user_id,
            period_type=period_type,
            period_key=period_key,
            api_calls=api_calls,
            compute_ms=compute_ms,
            cost_usd=cost_usd,
        )
    )
    await db_session.flush()


async def test_summary_structure(db_session):
    svc = BillingMetricsService(db_session)
    summary = await svc.get_summary()

    assert "today" in summary
    assert "this_month" in summary
    assert "subscribers" in summary
    assert "webhooks" in summary
    assert "top_users_by_cost" in summary
    assert "generated_at" in summary


async def test_today_totals_include_current_day_rows(db_session, db_user):
    today = date.today().isoformat()
    await _insert_usage(db_session, db_user.id, "day", today, 50, 100.0, 0.05)

    svc = BillingMetricsService(db_session)
    summary = await svc.get_summary()

    assert summary["today"]["api_calls"] >= 50
    assert summary["today"]["cost_usd"] >= 0.05


async def test_month_totals_include_current_month_rows(db_session, db_user):
    month = date.today().strftime("%Y-%m")
    await _insert_usage(db_session, db_user.id, "month", month, 200, 500.0, 0.25)

    svc = BillingMetricsService(db_session)
    summary = await svc.get_summary()

    assert summary["this_month"]["api_calls"] >= 200


async def test_subscriber_counts_reflect_user_statuses(db_session, db_user):
    db_user.subscription_status = "active"
    await db_session.flush()

    svc = BillingMetricsService(db_session)
    summary = await svc.get_summary()

    # At least one active subscriber
    assert summary["subscribers"].get("active", 0) >= 1


async def test_user_usage_returns_zeros_for_no_data(db_session, db_user):
    svc = BillingMetricsService(db_session)
    usage = await svc.get_user_usage(db_user.id)

    assert usage["user_id"] == str(db_user.id)
    assert usage["today"]["api_calls"] == 0
    assert usage["this_month"]["api_calls"] == 0


async def test_user_usage_reflects_inserted_rows(db_session, db_user):
    today = date.today().isoformat()
    month = date.today().strftime("%Y-%m")

    await _insert_usage(db_session, db_user.id, "day",   today,  75, 200.0, 0.10)
    await _insert_usage(db_session, db_user.id, "month", month, 300, 800.0, 0.40)

    svc = BillingMetricsService(db_session)
    usage = await svc.get_user_usage(db_user.id)

    assert usage["today"]["api_calls"] == 75
    assert usage["this_month"]["api_calls"] == 300


async def test_top_users_by_cost_are_ordered(db_session, db_user):
    from app.db.models.user import User

    month = date.today().strftime("%Y-%m")
    user2 = User(
        email=f"metrics_user2_{uuid.uuid4().hex[:6]}@test.com",
        hashed_password="$2b$12$fakehash",
        is_active=True,
        is_verified=True,
    )
    db_session.add(user2)
    await db_session.flush()

    # db_user: cost=1.0, user2: cost=5.0 — user2 should rank first
    await _insert_usage(db_session, db_user.id, "month", month, 100, 0.0, 1.0)
    await _insert_usage(db_session, user2.id, "month", month, 500, 0.0, 5.0)

    svc = BillingMetricsService(db_session)
    summary = await svc.get_summary()

    costs = [u["cost_usd"] for u in summary["top_users_by_cost"]]
    assert costs == sorted(costs, reverse=True), "Top users must be ordered by cost descending"


async def test_webhook_stats_counts_statuses(db_session):
    for status in ("processed", "processed", "failed"):
        db_session.add(WebhookEvent(
            stripe_event_id=f"evt_{uuid.uuid4().hex}",
            event_type="invoice.paid",
            payload="{}",
            status=status,
            attempts=1,
        ))
    await db_session.flush()

    svc = BillingMetricsService(db_session)
    summary = await svc.get_summary()

    assert summary["webhooks"].get("processed", 0) >= 2
    assert summary["webhooks"].get("failed", 0) >= 1

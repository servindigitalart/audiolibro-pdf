"""
Billing Safety Guards
=======================
Production protection layers that sit between HTTP handlers and the
billing engine.  All guards are stateless functions — no side effects,
no DB writes.

Guards:
  enforce_active_subscription  — block requests from non-paying users
  enforce_usage_limit          — reject before charging if quota is exceeded
  prevent_double_charge        — require a valid idempotency key on mutations
  require_stripe_customer      — ensure user has a Stripe customer ID

Design:
  - Raise HTTP 402 / 429 / 409 rather than silently degrading
  - All checks happen BEFORE any Stripe API call so we never charge then fail
  - Guards compose: layer them with FastAPI Depends() or call directly
"""
from __future__ import annotations

import uuid
from typing import Optional

from fastapi import HTTPException

from app.billing.constants import BILLABLE_STATUSES, TIER_DAILY_API_LIMITS, SubscriptionStatus
from app.db.models.user import User


# ── Active subscription guard ─────────────────────────────────────────────────

def enforce_active_subscription(user: User) -> None:
    """
    Raise HTTP 402 if the user's subscription is not in a billable state.

    SUSPENDED and CANCELED users cannot initiate new billing operations.
    """
    status_raw = user.subscription_status or SubscriptionStatus.FREE.value
    try:
        status = SubscriptionStatus(status_raw)
    except ValueError:
        raise HTTPException(
            status_code=402,
            detail=f"Unknown subscription status {status_raw!r}",
        )

    if status not in BILLABLE_STATUSES:
        raise HTTPException(
            status_code=402,
            detail=(
                f"Your subscription is {status.value}. "
                "Please update your payment method to continue."
            ),
        )


# ── Usage limit guard ─────────────────────────────────────────────────────────

def enforce_usage_limit(user: User, current_daily_calls: int) -> None:
    """
    Raise HTTP 429 if the user has exceeded their daily API quota.

    Called BEFORE the operation so we never charge for over-limit requests.
    Users on UNLIMITED (-1) plans are always allowed.
    """
    plan = (user.plan_tier or "FREE").upper()
    limit = TIER_DAILY_API_LIMITS.get(plan, TIER_DAILY_API_LIMITS["FREE"])

    if limit == -1:
        return  # Unlimited plan

    if current_daily_calls >= limit:
        raise HTTPException(
            status_code=429,
            detail=(
                f"Daily API limit of {limit} calls reached for your {plan} plan. "
                "Upgrade to increase your quota."
            ),
        )


# ── Double-charge prevention ──────────────────────────────────────────────────

def prevent_double_charge(idempotency_key: Optional[str]) -> str:
    """
    Require a non-empty idempotency key on billing mutation requests.

    Raises HTTP 409 if the key is missing or blank.
    Returns the validated key for downstream use.

    Callers should then pass the key to IdempotencyService.lock() which
    enforces uniqueness at the DB level.
    """
    if not idempotency_key or not idempotency_key.strip():
        raise HTTPException(
            status_code=409,
            detail=(
                "Idempotency-Key header is required for billing operations. "
                "Generate a UUID and retry."
            ),
        )
    return idempotency_key.strip()


# ── Stripe customer guard ─────────────────────────────────────────────────────

def require_stripe_customer(user: User) -> str:
    """
    Raise HTTP 422 if the user has no Stripe customer ID.

    Returns the customer ID for downstream use.
    """
    if not user.stripe_customer_id:
        raise HTTPException(
            status_code=422,
            detail=(
                "No payment method on file. "
                "Please complete the checkout flow before managing subscriptions."
            ),
        )
    return user.stripe_customer_id


# ── Composite guard for subscription mutations ────────────────────────────────

def guard_subscription_mutation(
    user: User,
    idempotency_key: Optional[str],
) -> tuple[str, str]:
    """
    Run all guards for subscription create/cancel/upgrade operations.

    Returns (stripe_customer_id, validated_idempotency_key).
    Raises the first 4xx it encounters.
    """
    enforce_active_subscription(user)
    customer_id = require_stripe_customer(user)
    validated_key = prevent_double_charge(idempotency_key)
    return customer_id, validated_key

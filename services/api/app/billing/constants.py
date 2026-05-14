"""
Billing Engine — Constants
==========================
Single source of truth for subscription states, transitions, tier limits,
webhook event types, and enforcement exemptions.
"""
from __future__ import annotations

from enum import Enum
from typing import FrozenSet


class SubscriptionStatus(str, Enum):
    FREE       = "free"
    TRIAL      = "trial"
    ACTIVE     = "active"
    PAST_DUE   = "past_due"
    CANCELED   = "canceled"
    SUSPENDED  = "suspended"


# Valid state-machine transitions.  Only edges listed here are allowed.
VALID_TRANSITIONS: dict[SubscriptionStatus, FrozenSet[SubscriptionStatus]] = {
    SubscriptionStatus.FREE:      frozenset({SubscriptionStatus.TRIAL, SubscriptionStatus.ACTIVE}),
    SubscriptionStatus.TRIAL:     frozenset({SubscriptionStatus.ACTIVE, SubscriptionStatus.CANCELED, SubscriptionStatus.PAST_DUE}),
    SubscriptionStatus.ACTIVE:    frozenset({SubscriptionStatus.PAST_DUE, SubscriptionStatus.CANCELED, SubscriptionStatus.SUSPENDED}),
    SubscriptionStatus.PAST_DUE:  frozenset({SubscriptionStatus.ACTIVE, SubscriptionStatus.CANCELED, SubscriptionStatus.SUSPENDED}),
    SubscriptionStatus.CANCELED:  frozenset({SubscriptionStatus.FREE, SubscriptionStatus.TRIAL, SubscriptionStatus.ACTIVE}),
    SubscriptionStatus.SUSPENDED: frozenset({SubscriptionStatus.ACTIVE, SubscriptionStatus.CANCELED}),
}


class WebhookEventType(str, Enum):
    INVOICE_PAID                     = "invoice.paid"
    INVOICE_PAYMENT_FAILED           = "invoice.payment_failed"
    CHECKOUT_SESSION_COMPLETED       = "checkout.session.completed"
    CUSTOMER_SUBSCRIPTION_CREATED    = "customer.subscription.created"
    CUSTOMER_SUBSCRIPTION_UPDATED    = "customer.subscription.updated"
    CUSTOMER_SUBSCRIPTION_DELETED    = "customer.subscription.deleted"
    CUSTOMER_SUBSCRIPTION_TRIAL_ENDING = "customer.subscription.trial_will_end"
    CHARGE_DISPUTE_CREATED           = "charge.dispute.created"


# Per-tier daily API-call quotas (enforced by BillingEnforcementMiddleware).
# -1 means unlimited.
TIER_DAILY_API_LIMITS: dict[str, int] = {
    "FREE":       100,
    "BASIC":    1_000,
    "PRO":     10_000,
    "ENTERPRISE": -1,
}

# Statuses that are allowed to make API calls at all.
BILLABLE_STATUSES: FrozenSet[SubscriptionStatus] = frozenset({
    SubscriptionStatus.FREE,
    SubscriptionStatus.TRIAL,
    SubscriptionStatus.ACTIVE,
    SubscriptionStatus.PAST_DUE,  # grace period: still allowed but flagged
})

# Paths exempt from billing enforcement (health, metrics, auth flows).
BILLING_EXEMPT_PATHS: FrozenSet[str] = frozenset({
    "/api/v1/health",
    "/api/v1/",
    "/api/v1/auth/login",
    "/api/v1/auth/register",
    "/api/v1/auth/refresh",
    "/api/v1/billing/webhook",
    "/metrics",
    "/docs",
    "/redoc",
    "/openapi.json",
})

# Redis key templates
USAGE_HOT_KEY = "billing:usage:{user_id}:{date}"     # date = YYYY-MM-DD
USAGE_MONTH_KEY = "billing:usage:{user_id}:{month}"  # month = YYYY-MM
IDEMPOTENCY_LOCK_KEY = "billing:idempotency:lock:{key}"
IDEMPOTENCY_RESULT_KEY = "billing:idempotency:result:{key}"
IDEMPOTENCY_TTL_SECONDS = 86_400 * 7  # 7 days

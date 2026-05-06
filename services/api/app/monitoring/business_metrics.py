"""
Business Metrics
================
Business-level metrics for tracking user activity and growth.
These are placeholders that hook into existing Block 2 auth logic only.
"""

from prometheus_client import Counter, Gauge

from app.monitoring.metrics import metrics_registry

# ============================================
# USER METRICS
# ============================================

registered_users_total = Gauge(
    "sonoro_registered_users_total",
    "Total number of registered users",
    registry=metrics_registry,
)

active_users_total = Gauge(
    "sonoro_active_users_total",
    "Total number of active users (logged in within 30 days)",
    registry=metrics_registry,
)

# ============================================
# AUTHENTICATION METRICS
# ============================================

auth_login_attempts_total = Counter(
    "sonoro_auth_login_attempts_total",
    "Total authentication login attempts",
    ["status"],  # status: success, failure
    registry=metrics_registry,
)

auth_login_failures_total = Counter(
    "sonoro_auth_login_failures_total",
    "Total authentication login failures",
    ["reason"],  # reason: invalid_credentials, account_locked, etc.
    registry=metrics_registry,
)

auth_token_refreshes_total = Counter(
    "sonoro_auth_token_refreshes_total",
    "Total token refresh operations",
    ["status"],  # status: success, failure
    registry=metrics_registry,
)

auth_registrations_total = Counter(
    "sonoro_auth_registrations_total",
    "Total user registrations",
    ["status"],  # status: success, failure
    registry=metrics_registry,
)

# ============================================
# HELPER FUNCTIONS
# ============================================
# These integrate with existing Block 2 auth logic without modifying it

def increment_login_attempt(success: bool) -> None:
    """
    Increment login attempt counter.
    Call this from auth endpoints without modifying business logic.
    """
    status = "success" if success else "failure"
    auth_login_attempts_total.labels(status=status).inc()


def increment_login_failure(reason: str = "invalid_credentials") -> None:
    """
    Increment login failure counter with reason.
    """
    auth_login_failures_total.labels(reason=reason).inc()


def increment_token_refresh(success: bool) -> None:
    """
    Increment token refresh counter.
    """
    status = "success" if success else "failure"
    auth_token_refreshes_total.labels(status=status).inc()


def increment_user_registration(success: bool) -> None:
    """
    Increment user registration counter.
    """
    status = "success" if success else "failure"
    auth_registrations_total.labels(status=status).inc()

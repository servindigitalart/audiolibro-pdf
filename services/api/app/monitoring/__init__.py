"""
Sonoro Monitoring Module
=========================
Observability, metrics, and monitoring infrastructure.
"""

from app.monitoring.metrics import (
    metrics_registry,
    http_requests_total,
    http_request_duration_seconds,
    http_exceptions_total,
    active_requests,
    db_connection_pool_size,
    db_connection_pool_overflow,
    redis_connection_status,
    redis_latency_seconds,
)
from app.monitoring.business_metrics import (
    registered_users_total,
    active_users_total,
    auth_login_attempts_total,
    auth_login_failures_total,
    increment_login_attempt,
    increment_login_failure,
    increment_user_registration,
)

__all__ = [
    "metrics_registry",
    "http_requests_total",
    "http_request_duration_seconds",
    "http_exceptions_total",
    "active_requests",
    "db_connection_pool_size",
    "db_connection_pool_overflow",
    "redis_connection_status",
    "redis_latency_seconds",
    "registered_users_total",
    "active_users_total",
    "auth_login_attempts_total",
    "auth_login_failures_total",
    "increment_login_attempt",
    "increment_login_failure",
    "increment_user_registration",
]

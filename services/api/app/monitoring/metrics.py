"""
Prometheus Metrics
==================
Core Prometheus metrics for infrastructure and application monitoring.
"""

from prometheus_client import Counter, Histogram, Gauge, CollectorRegistry

# Create a custom registry to avoid conflicts
metrics_registry = CollectorRegistry()

# ============================================
# HTTP METRICS
# ============================================

http_requests_total = Counter(
    "sonoro_http_requests_total",
    "Total HTTP requests by method, endpoint, and status",
    ["method", "endpoint", "status"],
    registry=metrics_registry,
)

http_request_duration_seconds = Histogram(
    "sonoro_http_request_duration_seconds",
    "HTTP request latency in seconds",
    ["method", "endpoint"],
    registry=metrics_registry,
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
)

http_exceptions_total = Counter(
    "sonoro_http_exceptions_total",
    "Total HTTP exceptions by type",
    ["exception_type"],
    registry=metrics_registry,
)

active_requests = Gauge(
    "sonoro_active_requests",
    "Number of currently active HTTP requests",
    registry=metrics_registry,
)

# ============================================
# DATABASE METRICS
# ============================================

db_connection_pool_size = Gauge(
    "sonoro_db_connection_pool_size",
    "Current database connection pool size",
    registry=metrics_registry,
)

db_connection_pool_overflow = Gauge(
    "sonoro_db_connection_pool_overflow",
    "Current database connection pool overflow",
    registry=metrics_registry,
)

db_connection_pool_checked_out = Gauge(
    "sonoro_db_connection_pool_checked_out",
    "Number of database connections currently checked out",
    registry=metrics_registry,
)

# ============================================
# REDIS METRICS
# ============================================

redis_connection_status = Gauge(
    "sonoro_redis_connection_status",
    "Redis connection status (1 = connected, 0 = disconnected)",
    registry=metrics_registry,
)

redis_latency_seconds = Gauge(
    "sonoro_redis_latency_seconds",
    "Redis ping latency in seconds",
    registry=metrics_registry,
)

redis_commands_total = Counter(
    "sonoro_redis_commands_total",
    "Total Redis commands executed",
    ["command"],
    registry=metrics_registry,
)

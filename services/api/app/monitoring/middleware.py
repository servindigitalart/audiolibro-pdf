"""
Metrics Middleware
==================
FastAPI middleware for automatic request/response metrics collection.
"""

import time
from typing import Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

from app.core import get_logger
from app.monitoring.metrics import (
    http_requests_total,
    http_request_duration_seconds,
    http_exceptions_total,
    active_requests,
)

logger = get_logger(__name__)


class MetricsMiddleware(BaseHTTPMiddleware):
    """
    Middleware to collect HTTP request/response metrics.
    
    Tracks:
    - Total requests by method, endpoint, and status
    - Request duration (histogram)
    - Active requests (gauge)
    - Exceptions
    """

    def __init__(self, app: ASGIApp):
        super().__init__(app)

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """Process request and collect metrics."""
        
        # Skip metrics for the /metrics endpoint itself to avoid recursion
        if request.url.path == "/metrics":
            return await call_next(request)

        # Extract request details
        method = request.method
        path = self._get_endpoint_path(request)
        
        # Increment active requests
        active_requests.inc()
        
        # Start timer
        start_time = time.time()
        
        try:
            # Process request
            response = await call_next(request)
            
            # Record metrics
            status = response.status_code
            duration = time.time() - start_time
            
            http_requests_total.labels(
                method=method,
                endpoint=path,
                status=status,
            ).inc()
            
            http_request_duration_seconds.labels(
                method=method,
                endpoint=path,
            ).observe(duration)
            
            return response
            
        except Exception as exc:
            # Record exception
            duration = time.time() - start_time
            exception_type = type(exc).__name__
            
            http_exceptions_total.labels(
                exception_type=exception_type,
            ).inc()
            
            # Still record the request with 500 status
            http_requests_total.labels(
                method=method,
                endpoint=path,
                status=500,
            ).inc()
            
            http_request_duration_seconds.labels(
                method=method,
                endpoint=path,
            ).observe(duration)
            
            logger.error(
                f"Exception in {method} {path}: {exception_type}",
                exc_info=True,
            )
            
            raise
            
        finally:
            # Decrement active requests
            active_requests.dec()

    def _get_endpoint_path(self, request: Request) -> str:
        """
        Extract endpoint path for metrics labeling.
        Normalizes dynamic path parameters to avoid high cardinality.
        """
        path = request.url.path
        
        # Normalize paths with IDs (e.g., /api/v1/users/123 -> /api/v1/users/{id})
        # This prevents high cardinality in Prometheus labels
        
        # For now, return the path as-is
        # In production, you may want to use request.scope.get("route") for matched route
        try:
            if hasattr(request, "scope") and "route" in request.scope:
                route = request.scope["route"]
                if hasattr(route, "path"):
                    return route.path
        except Exception:
            pass
        
        return path

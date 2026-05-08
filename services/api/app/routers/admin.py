"""
Admin Router
============
Administrative endpoints for runtime introspection and monitoring.
Protected by admin authentication.
"""

import os
import time
import psutil
from typing import Dict

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import get_logger, settings
from app.core.redis import get_redis
from app.core.auth_dependencies import require_admin
from app.db import get_db
from app.db.models import User
from app.schemas.runtime import RuntimeInfo, HealthCheck
from app.monitoring.metrics import metrics_registry, active_requests

logger = get_logger(__name__)

router = APIRouter(
    prefix="/api/v1/admin",
    tags=["admin"],
)

# Track application start time
_START_TIME = time.time()


@router.get(
    "/runtime",
    response_model=RuntimeInfo,
    summary="Get runtime information",
    description="Retrieve detailed runtime information for debugging and monitoring (admin only)",
)
async def get_runtime_info(
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> RuntimeInfo:
    """
    Get runtime information.
    
    **Requires**: Admin role
    
    Returns detailed information about:
    - Application uptime
    - Memory usage
    - Active connections
    - Request statistics
    - Environment configuration
    """
    try:
        # Calculate uptime
        uptime = time.time() - _START_TIME
        
        # Get memory usage
        process = psutil.Process(os.getpid())
        memory_info = process.memory_info()
        memory_mb = memory_info.rss / (1024 * 1024)  # Convert to MB
        
        # Get active connections
        connections = await _get_active_connections(db)
        
        # Get total requests from metrics
        total_requests = await _get_total_requests()
        
        # Get current active requests
        current_active = await _get_active_requests()
        
        return RuntimeInfo(
            uptime_seconds=uptime,
            environment=settings.app_env,
            version="0.2.0",  # SUB-BLOCK 3B version
            total_requests=total_requests,
            active_requests=current_active,
            memory_usage_mb=round(memory_mb, 2),
            active_connections=connections,
            feature_flags={
                "email_verification": settings.feature_email_verification,
                "rate_limiting": settings.feature_rate_limiting,
            },
        )
        
    except Exception as e:
        logger.error(f"Failed to get runtime info: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve runtime information",
        )


@router.get(
    "/health/detailed",
    response_model=HealthCheck,
    summary="Detailed health check",
    description="Get detailed health status of all services (admin only)",
)
async def detailed_health_check(
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> HealthCheck:
    """
    Detailed health check with individual service statuses.
    
    **Requires**: Admin role
    """
    services = {}
    
    # Check database
    try:
        await db.execute("SELECT 1")
        services["database"] = "healthy"
    except Exception as e:
        logger.error(f"Database health check failed: {e}")
        services["database"] = "unhealthy"
    
    # Check Redis
    try:
        if await get_redis():
            await (await get_redis()).ping()
            services["redis"] = "healthy"
        else:
            services["redis"] = "unavailable"
    except Exception as e:
        logger.error(f"Redis health check failed: {e}")
        services["redis"] = "unhealthy"
    
    # Check Sentry
    try:
        import sentry_sdk
        if sentry_sdk.Hub.current.client:
            services["sentry"] = "enabled"
        else:
            services["sentry"] = "disabled"
    except ImportError:
        services["sentry"] = "not_installed"
    
    # Overall status
    overall_status = "healthy" if all(
        s in ["healthy", "enabled", "disabled", "not_installed"] 
        for s in services.values()
    ) else "degraded"
    
    return HealthCheck(
        status=overall_status,
        services=services,
        uptime_seconds=time.time() - _START_TIME,
        version="0.2.0",
    )


# Helper functions

async def _get_active_connections(db: AsyncSession) -> Dict[str, int]:
    """Get active database and Redis connections."""
    connections = {}
    
    try:
        # Database connections
        pool = db.get_bind().pool
        connections["database"] = pool.checkedout()
    except Exception as e:
        logger.error(f"Failed to get DB connections: {e}")
        connections["database"] = 0
    
    try:
        # Redis connections
        if await get_redis():
            connections["redis"] = 1  # Single connection pool
        else:
            connections["redis"] = 0
    except Exception as e:
        logger.error(f"Failed to get Redis connections: {e}")
        connections["redis"] = 0
    
    return connections


async def _get_total_requests() -> int:
    """Get total number of requests from metrics."""
    try:
        # Get the metric from the registry
        for metric in metrics_registry.collect():
            if metric.name == "sonoro_http_requests_total":
                total = 0
                for sample in metric.samples:
                    if sample.name == "sonoro_http_requests_total_total":
                        total += sample.value
                return int(total)
        return 0
    except Exception as e:
        logger.error(f"Failed to get total requests: {e}")
        return 0


async def _get_active_requests() -> int:
    """Get current active requests from metrics."""
    try:
        # Get the current value of the active_requests gauge
        for metric in metrics_registry.collect():
            if metric.name == "sonoro_active_requests":
                for sample in metric.samples:
                    return int(sample.value)
        return 0
    except Exception as e:
        logger.error(f"Failed to get active requests: {e}")
        return 0

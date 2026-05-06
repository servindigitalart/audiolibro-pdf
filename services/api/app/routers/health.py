"""
Health Check Router
===================
Endpoints for monitoring application health and dependencies.
"""

from typing import Dict, Any

from fastapi import APIRouter, status, HTTPException
from sqlalchemy import text

from app.core.config import settings
from app.core.logging_config import get_logger
from app.core.redis import get_redis
from app.db.session import engine

logger = get_logger(__name__)

router = APIRouter(prefix="/api/v1", tags=["health"])


@router.get(
    "/health",
    response_model=Dict[str, Any],
    status_code=status.HTTP_200_OK,
    summary="Health check endpoint",
    description="Check if API and all critical dependencies (Database, Redis) are operational.",
)
async def health_check() -> Dict[str, Any]:
    """
    Comprehensive health check.

    Returns:
        dict: Health status of all services

    Raises:
        HTTPException: If any critical service is down
    """
    health_status = {
        "status": "healthy",
        "environment": settings.app_env,
        "debug": settings.debug,
        "services": {},
    }

    # Check Database
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        health_status["services"]["database"] = {
            "status": "healthy",
            "type": "postgresql",
        }
        logger.debug("Database health check passed")
    except Exception as e:
        logger.error(f"Database health check failed: {e}")
        health_status["status"] = "unhealthy"
        health_status["services"]["database"] = {
            "status": "unhealthy",
            "error": str(e),
        }

    # Check Redis
    try:
        redis_client = await get_redis()
        await redis_client.ping()
        health_status["services"]["redis"] = {
            "status": "healthy",
            "type": "redis",
        }
        logger.debug("Redis health check passed")
    except Exception as e:
        logger.error(f"Redis health check failed: {e}")
        health_status["status"] = "unhealthy"
        health_status["services"]["redis"] = {
            "status": "unhealthy",
            "error": str(e),
        }

    # Return 503 if any service is unhealthy
    if health_status["status"] == "unhealthy":
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=health_status,
        )

    return health_status


@router.get(
    "/",
    response_model=Dict[str, str],
    summary="Root endpoint",
    description="Simple API status check.",
)
async def root() -> Dict[str, str]:
    """
    Root endpoint - quick status check.

    Returns:
        dict: Basic API information
    """
    return {
        "service": "sonoro-api",
        "status": "running",
        "version": "0.1.0",
        "environment": settings.app_env,
    }

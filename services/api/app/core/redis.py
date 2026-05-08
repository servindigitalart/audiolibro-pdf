"""
Redis Client
============
Async Redis connection management.
"""

from typing import Optional

import redis.asyncio as redis
from redis.asyncio import Redis

from app.core.config import settings
from app.core.logging_config import get_logger

logger = get_logger(__name__)

# Global Redis client instance
_redis_client: Optional[Redis] = None


async def get_redis() -> Redis:
    """
    Get Redis client instance.

    Returns:
        Redis: Async Redis client

    Example:
        redis_client = await get_redis()
        await redis_client.set("key", "value")
        value = await redis_client.get("key")
    """
    global _redis_client

    if _redis_client is None:
        raise RuntimeError("Redis client not initialized. Call init_redis() first.")

    return _redis_client


async def init_redis() -> None:
    """
    Initialize Redis connection pool.
    Called during application startup.
    """
    global _redis_client

    try:
        _redis_client = redis.from_url(
            str(settings.redis_url),
            encoding="utf-8",
            decode_responses=True,
            max_connections=10,
        )

        # Test connection
        await _redis_client.ping()
        logger.info("Redis connection initialized successfully")
    except Exception as e:
        logger.error(f"Failed to initialize Redis: {e}")
        raise


async def close_redis() -> None:
    """
    Close Redis connection pool.
    Called during application shutdown.
    """
    global _redis_client

    if _redis_client:
        await _redis_client.close()
        logger.info("Redis connection closed")

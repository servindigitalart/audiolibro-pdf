"""
Rate Limiting Service
====================
Redis-based token bucket rate limiting with per-user and per-endpoint controls.
"""

import time
from dataclasses import dataclass
from enum import Enum
from typing import Optional

from redis.asyncio import Redis

from app.core.logging_config import get_logger

logger = get_logger(__name__)


class RateLimitExceeded(Exception):
    """Exception raised when rate limit is exceeded."""
    
    def __init__(
        self, 
        message: str, 
        retry_after: Optional[int] = None,
        limit: Optional[int] = None,
        window: Optional[int] = None
    ):
        super().__init__(message)
        self.retry_after = retry_after
        self.limit = limit
        self.window = window


class RateLimitTier(str, Enum):
    """Rate limit tiers for different endpoint categories."""
    AUTH = "auth"  # Login, registration endpoints
    UPLOAD = "upload"  # File upload endpoints
    API = "api"  # General API endpoints
    ADMIN = "admin"  # Admin endpoints


@dataclass
class RateLimitConfig:
    """Rate limit configuration for a specific tier."""
    requests_per_minute: int
    requests_per_hour: int
    requests_per_day: int
    burst_size: int  # Maximum burst allowed


# Default rate limit configurations by tier
DEFAULT_RATE_LIMITS = {
    RateLimitTier.AUTH: RateLimitConfig(
        requests_per_minute=5,
        requests_per_hour=20,
        requests_per_day=100,
        burst_size=10,
    ),
    RateLimitTier.UPLOAD: RateLimitConfig(
        requests_per_minute=10,
        requests_per_hour=50,
        requests_per_day=200,
        burst_size=15,
    ),
    RateLimitTier.API: RateLimitConfig(
        requests_per_minute=60,
        requests_per_hour=1000,
        requests_per_day=10000,
        burst_size=100,
    ),
    RateLimitTier.ADMIN: RateLimitConfig(
        requests_per_minute=120,
        requests_per_hour=5000,
        requests_per_day=50000,
        burst_size=200,
    ),
}


class RateLimitService:
    """
    Redis-based rate limiting service using token bucket algorithm.
    
    Features:
    - Per-user rate limiting
    - Multiple time windows (minute, hour, day)
    - Configurable burst sizes
    - Separate limits for different endpoint tiers
    """

    def __init__(self, redis: Redis):
        self.redis = redis
        self._rate_limits = DEFAULT_RATE_LIMITS.copy()

    def configure_limit(self, tier: RateLimitTier, config: RateLimitConfig):
        """Override default rate limit for a specific tier."""
        self._rate_limits[tier] = config
        logger.info(
            "rate_limit_configured",
            tier=tier,
            config=config,
        )

    async def check_rate_limit(
        self,
        user_id: str,
        tier: RateLimitTier,
        endpoint: Optional[str] = None,
    ) -> tuple[bool, Optional[int]]:
        """
        Check if request should be rate limited.
        
        Args:
            user_id: User identifier
            tier: Rate limit tier
            endpoint: Optional specific endpoint for granular limits
            
        Returns:
            Tuple of (is_allowed, retry_after_seconds)
            
        Raises:
            RateLimitExceeded: If rate limit is exceeded
        """
        config = self._rate_limits.get(tier, self._rate_limits[RateLimitTier.API])
        
        # Check all time windows
        windows = [
            ("minute", 60, config.requests_per_minute),
            ("hour", 3600, config.requests_per_hour),
            ("day", 86400, config.requests_per_day),
        ]
        
        for window_name, window_seconds, limit in windows:
            key = self._make_key(user_id, tier, window_name, endpoint)
            
            is_allowed, retry_after = await self._check_window(
                key, window_seconds, limit, config.burst_size
            )
            
            if not is_allowed:
                logger.warning(
                    "rate_limit_exceeded",
                    user_id=user_id,
                    tier=tier,
                    window=window_name,
                    limit=limit,
                    retry_after=retry_after,
                    endpoint=endpoint,
                )
                raise RateLimitExceeded(
                    f"Rate limit exceeded for {tier} ({limit} per {window_name})",
                    retry_after=retry_after,
                    limit=limit,
                    window=window_seconds,
                )
        
        return True, None

    async def _check_window(
        self,
        key: str,
        window_seconds: int,
        limit: int,
        burst_size: int,
    ) -> tuple[bool, Optional[int]]:
        """
        Check rate limit for a specific time window using token bucket.
        
        Uses Redis sorted sets for sliding window rate limiting.
        """
        now = time.time()
        window_start = now - window_seconds
        
        # Remove old entries
        await self.redis.zremrangebyscore(key, 0, window_start)
        
        # Count current requests in window
        current_count = await self.redis.zcard(key)
        
        if current_count >= limit:
            # Get oldest entry to calculate retry time
            oldest = await self.redis.zrange(key, 0, 0, withscores=True)
            if oldest:
                retry_after = int(oldest[0][1] + window_seconds - now) + 1
                return False, retry_after
            return False, window_seconds
        
        # Add current request
        await self.redis.zadd(key, {str(now): now})
        
        # Set expiration on the key
        await self.redis.expire(key, window_seconds)
        
        return True, None

    async def increment(
        self,
        user_id: str,
        tier: RateLimitTier,
        endpoint: Optional[str] = None,
    ):
        """
        Increment rate limit counter (called after successful request).
        
        Note: This is automatically done by check_rate_limit(), so you
        typically don't need to call this manually.
        """
        config = self._rate_limits.get(tier, self._rate_limits[RateLimitTier.API])
        
        windows = [
            ("minute", 60),
            ("hour", 3600),
            ("day", 86400),
        ]
        
        now = time.time()
        
        for window_name, window_seconds in windows:
            key = self._make_key(user_id, tier, window_name, endpoint)
            await self.redis.zadd(key, {str(now): now})
            await self.redis.expire(key, window_seconds)

    async def get_limits(
        self,
        user_id: str,
        tier: RateLimitTier,
        endpoint: Optional[str] = None,
    ) -> dict:
        """
        Get current rate limit status for a user.
        
        Returns:
            Dictionary with limit info for each time window
        """
        config = self._rate_limits.get(tier, self._rate_limits[RateLimitTier.API])
        
        windows = [
            ("minute", 60, config.requests_per_minute),
            ("hour", 3600, config.requests_per_hour),
            ("day", 86400, config.requests_per_day),
        ]
        
        result = {}
        
        for window_name, window_seconds, limit in windows:
            key = self._make_key(user_id, tier, window_name, endpoint)
            now = time.time()
            window_start = now - window_seconds
            
            # Remove old entries
            await self.redis.zremrangebyscore(key, 0, window_start)
            
            # Count current requests
            current = await self.redis.zcard(key)
            
            result[window_name] = {
                "limit": limit,
                "remaining": max(0, limit - current),
                "used": current,
                "reset_at": int(now + window_seconds),
            }
        
        return result

    async def reset(
        self,
        user_id: str,
        tier: RateLimitTier,
        endpoint: Optional[str] = None,
    ):
        """Reset rate limits for a user (admin operation)."""
        windows = ["minute", "hour", "day"]
        
        for window_name in windows:
            key = self._make_key(user_id, tier, window_name, endpoint)
            await self.redis.delete(key)
        
        logger.info(
            "rate_limit_reset",
            user_id=user_id,
            tier=tier,
            endpoint=endpoint,
        )

    def _make_key(
        self,
        user_id: str,
        tier: RateLimitTier,
        window: str,
        endpoint: Optional[str] = None,
    ) -> str:
        """Generate Redis key for rate limit tracking."""
        base = f"ratelimit:{tier.value}:{user_id}:{window}"
        if endpoint:
            return f"{base}:{endpoint}"
        return base

"""
Rate Limit Dependencies
=======================
FastAPI wiring for the existing `RateLimitService`.

This module adds no rate-limiting logic of its own — `RateLimitService` was
already implemented, tested, and configured with an UPLOAD tier, but had zero
production callers (F-29).  All this does is put it in front of the endpoints
that spend money.

Failure policy — fail OPEN, deliberately
----------------------------------------
If Redis is unreachable the request is allowed through and logged loudly.  This
is the opposite of the cost guard's fail-closed policy, and the difference is
intentional: rate limiting bounds *abuse rate*, while the Phase 0C cost guard
bounds *money* and runs regardless of Redis.  A Redis outage must not stop every
customer from converting a book when spend is already capped elsewhere.
"""
from __future__ import annotations

import logging
from typing import Callable

from fastapi import Depends, HTTPException, Request, status

from app.core.auth_dependencies import get_current_active_user
from app.core.config import settings
from app.core.redis import get_redis
from app.db.models.user import User
from app.financial.rate_limit.rate_limit_service import (
    RateLimitExceeded,
    RateLimitService,
    RateLimitTier,
)

# stdlib logger, not app.core.logging_config.get_logger: the [SONORO] lines below
# are %-style, which the structlog BoundLogger that get_logger returns rejects.
# Same choice as app/financial/cost/cost_guard.py.
logger = logging.getLogger(__name__)


def rate_limit(tier: RateLimitTier) -> Callable:
    """
    Build a FastAPI dependency enforcing *tier*'s limits for the current user.

    Attach it to the route, not the handler body, so the limit is visible in the
    route definition and cannot be skipped by an early return:

        @router.post("/upload", dependencies=[Depends(rate_limit(RateLimitTier.UPLOAD))])
    """

    async def _enforce(
        request: Request,
        current_user: User = Depends(get_current_active_user),
    ) -> None:
        if not settings.feature_rate_limiting:
            return

        endpoint = request.url.path

        try:
            redis = await get_redis()
            service = RateLimitService(redis)
            # No `endpoint=` on purpose: that would give upload, process and
            # retry a bucket each, letting one user create 3× the intended
            # number of paid jobs per minute.  One shared tier bucket.
            await service.check_rate_limit(user_id=str(current_user.id), tier=tier)
        except RateLimitExceeded as e:
            logger.warning(
                "[SONORO] rate_limit_rejected user_id=%s tier=%s endpoint=%s retry_after=%s",
                current_user.id, tier.value, endpoint, e.retry_after,
            )
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=(
                    "Too many requests. Please wait a moment and try again."
                ),
                headers={"Retry-After": str(e.retry_after or 60)},
            ) from e
        except Exception as e:
            # Redis down, or any other infrastructure failure.  Allow the
            # request — see the fail-open rationale in the module docstring.
            logger.error(
                "[SONORO] rate_limit_degraded user_id=%s tier=%s endpoint=%s error=%s "
                "— allowing request",
                current_user.id, tier.value, endpoint, e,
            )

    return _enforce

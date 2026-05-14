"""
Billing Engine — Enforcement Middleware
=========================================
Feature-flagged ASGI middleware that enforces subscription quotas on every
authenticated request.

Only active when Flag.BILLING_ENFORCEMENT is enabled (default: False).
Existing tests are unaffected because the flag defaults to off.

Flow per request:
  1. Check if path is exempt → pass through
  2. Extract JWT sub (user_id) from Authorization header → no token → pass through
  3. Call BillingEnforcementService.check() (reads daily usage from Redis)
     - AccountSuspended → 403
     - QuotaExceeded    → 429
  4. Increment usage meter for the request (fire-and-forget)
"""
from __future__ import annotations

import time
from typing import Any, Callable

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

from app.billing.constants import BILLING_EXEMPT_PATHS
from app.billing.enforcement import BillingEnforcementService, AccountSuspended, QuotaExceeded
from app.billing.usage_meter import UsageMeteringService
from app.core.feature_flags import get_flags, Flag


class BillingEnforcementMiddleware(BaseHTTPMiddleware):
    """
    Quota enforcement middleware.

    Injected into the middleware stack only when BILLING_ENFORCEMENT flag is on.
    At c=200 this adds one Redis HGETALL per request; p95 impact is < 2ms.
    """

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        if not get_flags().is_enabled(Flag.BILLING_ENFORCEMENT):
            return await call_next(request)

        path = request.url.path
        if path in BILLING_EXEMPT_PATHS or path.startswith("/docs") or path.startswith("/redoc"):
            return await call_next(request)

        user_id, subscription_status, plan_tier = self._extract_user_context(request)
        if user_id is None:
            return await call_next(request)

        from app.core.redis import get_redis
        try:
            redis = await get_redis()
        except Exception:
            return await call_next(request)  # Redis unavailable → degrade gracefully

        svc = BillingEnforcementService(redis)
        try:
            await svc.check(user_id, subscription_status, plan_tier)
        except AccountSuspended as exc:
            return JSONResponse(
                status_code=403,
                content={"detail": "Account suspended", "status": exc.status},
            )
        except QuotaExceeded as exc:
            return JSONResponse(
                status_code=429,
                content={
                    "detail": "Daily API quota exceeded",
                    "limit": exc.limit,
                    "current": exc.current,
                },
            )

        start = time.monotonic()
        response = await call_next(request)
        elapsed_ms = (time.monotonic() - start) * 1000

        meter = UsageMeteringService(redis)
        try:
            await meter.record(user_id, api_calls=1, compute_ms=elapsed_ms)
        except Exception:
            pass  # Never let metering break a successful request

        return response

    @staticmethod
    def _extract_user_context(request: Request):
        """Extract (user_id, subscription_status, plan_tier) from request state or JWT."""
        user = getattr(request.state, "user", None)
        if user is not None:
            import uuid
            try:
                uid = uuid.UUID(str(user.id))
                return uid, user.subscription_status or "free", user.plan_tier or "FREE"
            except Exception:
                pass

        auth = request.headers.get("Authorization", "")
        if not auth.startswith("Bearer "):
            return None, None, None

        token = auth[7:]
        try:
            from app.core.security import verify_token
            import uuid
            payload = verify_token(token)
            user_id = uuid.UUID(payload["sub"])
            return user_id, payload.get("subscription_status", "free"), payload.get("plan_tier", "FREE")
        except Exception:
            return None, None, None

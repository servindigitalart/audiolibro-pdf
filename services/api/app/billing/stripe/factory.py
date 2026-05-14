"""
Stripe Provider Factory
========================
Returns the correct StripeProvider implementation based on STRIPE_MODE.

  STRIPE_MODE=mock  → MockStripeClient  (default; no API key required)
  STRIPE_MODE=real  → RealStripeClient  (requires STRIPE_SECRET_KEY)

The provider is constructed fresh on each call — callers should cache it
at request or application scope, not call this at module import time.

Environment variables (via Settings):
  STRIPE_MODE         = "mock" | "real"
  STRIPE_SECRET_KEY   = "sk_live_xxx" or "sk_test_xxx"

Switching modes requires only environment changes — no code changes.
"""
from __future__ import annotations

from functools import lru_cache

from app.billing.stripe.base import StripeProvider


def get_stripe_provider() -> StripeProvider:
    """
    Instantiate and return the Stripe provider for the current STRIPE_MODE.

    Called at request time (not at import time) so the settings are read
    after the environment is fully loaded.
    """
    from app.core.config import settings

    mode = getattr(settings, "stripe_mode", "mock").lower()

    if mode == "mock":
        from app.billing.stripe.mock import MockStripeClient
        return MockStripeClient()

    if mode == "real":
        if not settings.stripe_secret_key:
            raise RuntimeError(
                "STRIPE_MODE=real requires STRIPE_SECRET_KEY to be set. "
                "Set it in your .env file or environment."
            )
        from app.billing.stripe.real import RealStripeClient
        return RealStripeClient(api_key=settings.stripe_secret_key)

    raise ValueError(
        f"Unknown STRIPE_MODE={mode!r}. "
        "Valid values: 'mock' (default) or 'real'."
    )


@lru_cache(maxsize=1)
def get_cached_stripe_provider() -> StripeProvider:
    """
    Application-scoped singleton provider.

    Use this for long-lived callers (e.g. background jobs) that want to
    reuse a single instance.  Not suitable for per-request use where you
    need a fresh MockStripeClient per test.
    """
    return get_stripe_provider()

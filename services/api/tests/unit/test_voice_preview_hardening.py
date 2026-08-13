"""
Unit Tests: Voice Preview Hardening (Phase 0E / audit 0.9 follow-up)
====================================================================
`/voices/preview` is the one paid TTS path that does not go through TTSService,
so it has no cost guard, no cost ledger and no per-chunk retry policy.  That
bypass is deliberate — a preview is a fixed ~90-char string — but it left two
ways for caller-supplied input to force unbounded paid work:

  1. No rate limit at all, on the only money endpoint without one.
  2. The cache key used the RAW narration_style string, while get_style_params
     maps every unknown style to DEFAULT_PARAMS.  `?narration_style=foo|bar|baz`
     therefore produced identical audio from three separate paid calls, and
     three permanent entries in a process-global dict.

These tests pin both fixes, plus the properties that had to survive them:
authentication, synchronous response, and unchanged behaviour for real styles.
"""
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.routers import voices
from app.services.tts.narration_style import (
    DEFAULT_PARAMS,
    STYLE_MAP,
    get_style_params,
)

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _clean_cache():
    """Each test starts from an empty preview cache."""
    voices._cache.clear()
    yield
    voices._cache.clear()


def _route():
    for route in voices.router.routes:
        if getattr(route, "path", None) == "/api/v1/voices/preview":
            return route
    raise AssertionError("preview route not found")


# ── 1. The route is rate limited, with the API tier ───────────────────────────


def test_preview_route_carries_a_rate_limit():
    """
    Declared on the route so a handler edit cannot silently drop it — the same
    rule the Phase 0D money endpoints follow.
    """
    deps = getattr(_route(), "dependencies", [])
    assert any(
        "_enforce" in getattr(d.dependency, "__name__", "") for d in deps
    ), "preview must carry the rate_limit dependency"


def test_preview_uses_the_api_tier_not_a_new_one():
    """
    RateLimitTier.API is the existing tier for authenticated API usage.  UPLOAD
    (10/min) would be wrong: a user auditioning voices in the picker legitimately
    fires more previews than they do uploads.
    """
    from app.financial.rate_limit.rate_limit_service import (
        DEFAULT_RATE_LIMITS,
        RateLimitTier,
    )

    dep = next(
        d for d in _route().dependencies
        if "_enforce" in getattr(d.dependency, "__name__", "")
    )
    # The tier is captured in the closure built by rate_limit(tier).
    captured = dep.dependency.__closure__[0].cell_contents
    assert captured is RateLimitTier.API
    assert DEFAULT_RATE_LIMITS[RateLimitTier.API].requests_per_minute == 60


@pytest.mark.asyncio
async def test_rate_limit_is_actually_invoked():
    """The dependency must reach RateLimitService, not just be declared."""
    from app.financial.rate_limit.dependencies import rate_limit
    from app.financial.rate_limit.rate_limit_service import RateLimitTier
    from tests.fakes import FakeRedis

    dep = rate_limit(RateLimitTier.API)
    request = SimpleNamespace(url=SimpleNamespace(path="/api/v1/voices/preview"))
    user = SimpleNamespace(id=uuid4())

    with patch(
        "app.financial.rate_limit.dependencies.settings.feature_rate_limiting", True
    ):
        with patch(
            "app.financial.rate_limit.dependencies.get_redis",
            new_callable=AsyncMock, return_value=FakeRedis(),
        ) as mock_redis:
            assert await dep(request, user) is None
    mock_redis.assert_awaited()


@pytest.mark.asyncio
async def test_exceeding_the_api_tier_raises_429():
    from app.financial.rate_limit.dependencies import rate_limit
    from app.financial.rate_limit.rate_limit_service import RateLimitTier
    from tests.fakes import FakeRedis

    dep = rate_limit(RateLimitTier.API)
    request = SimpleNamespace(url=SimpleNamespace(path="/api/v1/voices/preview"))
    user = SimpleNamespace(id=uuid4())
    redis = FakeRedis()

    async def call():
        with patch(
            "app.financial.rate_limit.dependencies.settings.feature_rate_limiting", True
        ):
            with patch(
                "app.financial.rate_limit.dependencies.get_redis",
                new_callable=AsyncMock, return_value=redis,
            ):
                return await dep(request, user)

    for _ in range(60):          # exhaust the API per-minute allowance
        await call()

    with pytest.raises(HTTPException) as exc:
        await call()
    assert exc.value.status_code == 429


# ── 2. Authentication is unchanged ────────────────────────────────────────────


def test_preview_still_requires_an_authenticated_user():
    """Hardening must not have loosened the existing auth requirement."""
    import inspect

    sig = inspect.signature(voices.preview_voice)
    assert "current_user" in sig.parameters
    assert sig.parameters["current_user"].default.dependency.__name__ == (
        "get_current_active_user"
    )


# ── 3. Cache key is derived from resolved params, not raw input ───────────────


def test_unknown_styles_resolve_to_default_params():
    """Pre-existing behaviour that the key fix depends on — pinned explicitly."""
    assert get_style_params("foo") == DEFAULT_PARAMS
    assert get_style_params("bar") == DEFAULT_PARAMS
    assert get_style_params(None) == DEFAULT_PARAMS
    assert get_style_params("") == DEFAULT_PARAMS


def test_equivalent_unknown_styles_share_one_cache_key():
    """
    This is the defect: three junk styles, one set of synthesis parameters, so
    one cache entry and one paid provider call — not three.
    """
    keys = {
        voices._cache_key("en-US-Neural2-A", "en-US", get_style_params(s))
        for s in ("foo", "bar", "baz", "", None)
    }
    assert len(keys) == 1


def test_distinct_real_styles_keep_distinct_keys():
    """Valid styles must not collapse — they produce genuinely different audio."""
    keys = {
        voices._cache_key("en-US-Neural2-A", "en-US", get_style_params(style))
        for style in STYLE_MAP
    }
    assert len(keys) == len(STYLE_MAP)


def test_unknown_style_shares_the_key_of_an_absent_style():
    """`?narration_style=junk` must reuse the plain default preview, not add one."""
    assert voices._cache_key(
        "en-US-Neural2-A", "en-US", get_style_params("junk")
    ) == voices._cache_key("en-US-Neural2-A", "en-US", get_style_params(None))


def test_voice_and_language_still_separate_entries():
    """The key fix must not over-collapse: different voices are different audio."""
    a = voices._cache_key("en-US-Neural2-A", "en-US", DEFAULT_PARAMS)
    b = voices._cache_key("es-US-Neural2-A", "es-US", DEFAULT_PARAMS)
    assert a != b


def test_cache_key_excludes_the_raw_style_string():
    """Regression guard: the untrusted string must not appear in the key."""
    key = voices._cache_key(
        "en-US-Neural2-A", "en-US", get_style_params("totally-made-up-style")
    )
    assert "totally-made-up-style" not in key


# ── 4. The cache is bounded ───────────────────────────────────────────────────


def test_cache_is_bounded_and_evicts_least_recently_used():
    """
    voice_id stays caller-supplied and Google publishes ~1600 voices, so the
    key fix alone does not bound the dict.  The LRU ceiling does.
    """
    from collections import OrderedDict

    assert isinstance(voices._cache, OrderedDict)
    assert voices._CACHE_MAX_ENTRIES > 0

    # Reproduce the handler's write path for more entries than the ceiling.
    for i in range(voices._CACHE_MAX_ENTRIES + 25):
        voices._cache[f"voice-{i}"] = b"audio"
        voices._cache.move_to_end(f"voice-{i}")
        while len(voices._cache) > voices._CACHE_MAX_ENTRIES:
            voices._cache.popitem(last=False)

    assert len(voices._cache) == voices._CACHE_MAX_ENTRIES
    assert "voice-0" not in voices._cache            # oldest evicted
    assert f"voice-{voices._CACHE_MAX_ENTRIES + 24}" in voices._cache  # newest kept


# ── 5. Provider behaviour and latency are unchanged ───────────────────────────


def test_preview_remains_synchronous_and_direct():
    """
    Preview must NOT have been routed through Celery or TTSService: it stays a
    synchronous provider call so the picker returns audio in one round trip.
    """
    import inspect

    src = inspect.getsource(voices)
    assert "GoogleTTSProvider()" in src
    assert "provider.synthesize(" in src
    assert "delay(" not in src and "apply_async" not in src
    assert inspect.iscoroutinefunction(voices.preview_voice)


def test_preview_writes_no_cost_event():
    """
    Deliberate: a per-preview DB row would cost more than the ~$0.0014 preview.
    The rate limit is the ceiling here, not the ledger.
    """
    import inspect

    src = inspect.getsource(voices)
    assert "CostTracker" not in src
    assert "track_event" not in src

"""
Unit Tests: TTS retry containment (F-2)
=======================================
Regression tests for the retry storm:

  Old behaviour: any failure bubbled out of the job, Celery's
  `autoretry_for=(Exception,)` fired, and the pipeline restarted at step 1 —
  re-synthesizing every chunk already paid for.  A book failing at 95% billed
  Google 4×.

  New behaviour:
    - No job-level auto-retry (the pipeline has no checkpoint to resume from).
    - Transient provider failures are retried per chunk, so one 503 costs one
      chunk instead of one book.
    - Permanent failures fail fast rather than being billed three times.

Pure unit tests — no real provider, no DB, no sleeping.
"""
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from app.services.tts.base import (
    TTSInvalidInputError,
    TTSNetworkError,
    TTSProvider,
    TTSProviderError,
    TTSQuotaExceededError,
)
from app.services.tts.tts_service import _MAX_SYNTHESIS_ATTEMPTS, TTSService

pytestmark = pytest.mark.unit


class FlakyProvider(TTSProvider):
    """Fails with *errors* in order, then succeeds."""

    def __init__(self, errors):
        self.errors = list(errors)
        self.call_count = 0

    async def synthesize(self, text, voice_id, language_code,
                         speaking_rate=1.0, pitch=0.0) -> bytes:
        self.call_count += 1
        if self.errors:
            raise self.errors.pop(0)
        return b"audio"

    def estimate_cost(self, n):
        return 0.0

    def get_provider_name(self):
        return "fake"


def _net_error():
    return TTSNetworkError("503 backend unavailable", provider="fake")


async def _synthesize(provider):
    """Run one synthesis with backoff sleeps stubbed out.

    Returns (audio_bytes, delays_slept) so tests can assert on the backoff
    without re-inlining the call.
    """
    service = TTSService(provider=provider)
    with patch(
        "app.services.tts.tts_service.asyncio.sleep", new_callable=AsyncMock
    ) as mock_sleep:
        audio = await service.synthesize_text(
            db=AsyncMock(),
            user_id=uuid4(),
            text="Hello",
            voice_id="v1",
            language_code="en-US",
        )
    return audio, [call.args[0] for call in mock_sleep.await_args_list]


# ── Transient failures are retried in place ───────────────────────────────────

@pytest.mark.asyncio
async def test_transient_failure_is_retried_with_growing_backoff():
    """Two 503s then success → the chunk is delivered, not lost."""
    provider = FlakyProvider([_net_error(), _net_error()])

    audio, delays = await _synthesize(provider)

    assert audio == b"audio"
    assert provider.call_count == 3
    # Growing waits, so a struggling provider is not hammered.
    assert delays == [2.0, 4.0]


@pytest.mark.asyncio
async def test_quota_exceeded_is_retried():
    """ResourceExhausted is a rate limit — backoff is exactly the right cure."""
    provider = FlakyProvider([TTSQuotaExceededError("429 rate limited", provider="fake")])

    audio, _ = await _synthesize(provider)

    assert audio == b"audio"
    assert provider.call_count == 2


@pytest.mark.asyncio
async def test_retries_are_bounded():
    """A permanently unavailable provider must not be retried forever."""
    provider = FlakyProvider([_net_error() for _ in range(10)])

    with pytest.raises(TTSNetworkError):
        await _synthesize(provider)

    assert provider.call_count == _MAX_SYNTHESIS_ATTEMPTS


# ── Permanent failures fail fast ──────────────────────────────────────────────

@pytest.mark.asyncio
@pytest.mark.parametrize("error", [
    TTSInvalidInputError("text too long", provider="fake"),
    TTSProviderError("something else", provider="fake"),
])
async def test_permanent_failure_is_not_retried(error):
    """A failure that will repeat identically gets billed once, not three times."""
    provider = FlakyProvider([error])

    with pytest.raises(TTSProviderError):
        await _synthesize(provider)

    assert provider.call_count == 1


# ── Cost is recorded once per delivered chunk, not once per attempt ───────────

@pytest.mark.asyncio
async def test_failed_attempts_do_not_record_cost():
    """Google does not bill a 503, so neither should the cost ledger."""
    provider = FlakyProvider([_net_error(), _net_error()])

    with patch(
        "app.services.tts.tts_service.CostTracker.track_event", new_callable=AsyncMock
    ) as mock_track:
        await _synthesize(provider)

    assert mock_track.await_count == 1


# ── No job-level auto-retry ───────────────────────────────────────────────────

def test_processing_task_has_no_autoretry():
    """
    `autoretry_for` on the processing task re-runs the whole pipeline with no
    checkpoint, re-synthesizing every already-paid chunk.  Re-add it only once
    a retry can resume instead of restarting.
    """
    from app.tasks.processing import process_document_job

    assert not getattr(process_document_job, "autoretry_for", ()), (
        "process_document_job has autoretry_for set — a job-level retry "
        "re-synthesizes the entire book (F-2). Retry per chunk instead."
    )
    assert getattr(process_document_job, "max_retries", 0) in (0, None), (
        "process_document_job still allows Celery retries."
    )

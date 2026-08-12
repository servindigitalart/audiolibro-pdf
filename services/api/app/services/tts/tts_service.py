"""
TTS Service Layer
=================
BLOCK 6A: High-level service for Text-to-Speech operations.

This service:
- Orchestrates TTS provider calls
- Tracks character usage and costs
- Integrates with cost governance
- Emits Prometheus metrics
- Handles errors gracefully

Does NOT handle:
- Chapter detection (future)
- Audio concatenation (future)
- Caching (future)
- Multi-provider routing (future)
"""

import asyncio
import logging
import time
from typing import Optional
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.financial.cost.cost_tracker import CostTracker
from app.financial.cost.cost_enums import CostEventType, CostProvider
from app.services.tts.base import (
    TTSNetworkError,
    TTSProvider,
    TTSProviderError,
    TTSQuotaExceededError,
)
from app.services.tts.google_provider import GoogleTTSProvider
from app.pricing.unit_economics import tts_cost_for_voice
from app.financial.financial_metrics import (
    cost_events_total,
)

logger = logging.getLogger(__name__)


# ============================================
# PER-CHUNK RETRY POLICY
# ============================================
# A transient provider failure used to bubble all the way up and fail the whole
# job, which Celery then retried from step 1 — re-synthesizing every chunk
# already paid for.  Retrying here instead means one 503 costs one chunk.
#
# Only transient subclasses are retried.  TTSInvalidInputError (bad text/voice)
# and bare TTSProviderError (unknown cause) fail fast: retrying a permanent
# error just bills the same failure three times.
_RETRYABLE_ERRORS = (TTSNetworkError, TTSQuotaExceededError)
_MAX_SYNTHESIS_ATTEMPTS = 3
_RETRY_BACKOFF_SECONDS = 2.0  # attempt 1 waits 2s, attempt 2 waits 4s


# ============================================
# TTS METRICS (BLOCK 6A)
# ============================================

from prometheus_client import Counter, Histogram
from app.monitoring.metrics import metrics_registry

tts_requests_total = Counter(
    "sonoro_tts_requests_total",
    "Total TTS synthesis requests",
    ["provider", "status"],
    registry=metrics_registry,
)

tts_characters_total = Counter(
    "sonoro_tts_characters_total",
    "Total characters synthesized",
    ["provider"],
    registry=metrics_registry,
)

tts_cost_usd_total = Counter(
    "sonoro_tts_cost_usd_total",
    "Total TTS cost in USD",
    ["provider"],
    registry=metrics_registry,
)

tts_failures_total = Counter(
    "sonoro_tts_failures_total",
    "Total TTS failures",
    ["provider", "failure_reason"],
    registry=metrics_registry,
)

tts_latency_seconds = Histogram(
    "sonoro_tts_latency_seconds",
    "TTS synthesis latency in seconds",
    ["provider"],
    registry=metrics_registry,
)


# ============================================
# TTS SERVICE
# ============================================

class TTSService:
    """
    High-level TTS service.
    
    Responsibilities:
    - Provider selection and initialization
    - Cost estimation and tracking
    - Metrics emission
    - Error handling
    - Integration with cost governance
    
    Usage:
        service = TTSService()
        audio_bytes = await service.synthesize_text(
            db=db,
            user_id=user_id,
            text="Hello world",
            voice_id="en-US-Neural2-A",
            language_code="en-US"
        )
    """
    
    def __init__(self, provider: Optional[TTSProvider] = None):
        """
        Initialize TTS service.
        
        Args:
            provider: Optional custom provider (defaults to Google TTS)
        """
        if provider:
            self.provider = provider
        else:
            # Default to Google Cloud TTS
            self.provider = GoogleTTSProvider()
        
        logger.info(f"TTS Service initialized with provider: {self.provider.get_provider_name()}")
    
    async def synthesize_text(
        self,
        db: AsyncSession,
        user_id: UUID,
        text: str,
        voice_id: Optional[str] = None,
        language_code: Optional[str] = None,
        speaking_rate: float = 1.0,
        pitch: float = 0.0,
        document_id: Optional[UUID] = None,
        job_id: Optional[UUID] = None,
    ) -> bytes:
        """
        Synthesize text to speech with full tracking.
        
        This method:
        1. Validates input
        2. Counts characters
        3. Estimates cost
        4. Calls provider
        5. Records cost event
        6. Emits metrics
        
        Args:
            db: Database session for cost tracking
            user_id: User requesting synthesis
            text: Text to synthesize
            voice_id: Voice identifier (uses default if not provided)
            language_code: Language code (uses default if not provided)
            
        Returns:
            MP3 audio data as bytes
            
        Raises:
            TTSProviderError: If synthesis fails
        """
        # Use defaults if not provided
        if not voice_id:
            voice_id = settings.google_tts_default_voice
        if not language_code:
            language_code = settings.google_tts_default_language
        
        # Count characters
        character_count = len(text)

        # Price the voice actually being used, not the provider's flat rate.
        # GoogleTTSProvider.COST_PER_CHARACTER hardcodes the Neural2 rate, which
        # over-states cost by 4× if a Standard voice is ever selected.  The
        # ledger and the pre-generation guard must agree on one rate.
        unit_cost = tts_cost_for_voice(1, voice_id)
        estimated_cost = tts_cost_for_voice(character_count, voice_id)

        logger.info(
            f"Starting TTS synthesis",
            extra={
                "user_id": str(user_id),
                "character_count": character_count,
                "estimated_cost_usd": estimated_cost,
                "provider": self.provider.get_provider_name(),
                "voice_id": voice_id,
                "language_code": language_code,
            }
        )
        
        start_time = time.time()
        attempt = 1

        try:
            # Call provider, retrying transient failures in place so a single
            # 503 does not discard every chunk synthesized so far.
            for attempt in range(1, _MAX_SYNTHESIS_ATTEMPTS + 1):
                try:
                    audio_bytes = await self.provider.synthesize(
                        text=text,
                        voice_id=voice_id,
                        language_code=language_code,
                        speaking_rate=speaking_rate,
                        pitch=pitch,
                    )
                    break
                except _RETRYABLE_ERRORS as e:
                    if attempt == _MAX_SYNTHESIS_ATTEMPTS:
                        raise
                    # Record the failed attempt so retries stay countable.  It
                    # carries zero cost — the provider does not bill a 503.
                    await self._record_failed_attempt(
                        db, user_id, character_count, unit_cost, voice_id,
                        e, attempt, document_id, job_id,
                    )
                    delay = _RETRY_BACKOFF_SECONDS ** attempt
                    logger.warning(
                        "[SONORO] tts_chunk_retry attempt=%d/%d delay=%.1fs "
                        "chars=%d error_type=%s error=%s",
                        attempt, _MAX_SYNTHESIS_ATTEMPTS, delay,
                        character_count, e.__class__.__name__, str(e),
                    )
                    await asyncio.sleep(delay)

            # Calculate actual duration
            duration = time.time() - start_time

            # Record the delivered chunk — exactly once, however many provider
            # attempts it took.  A retry must never become a second charge.
            await CostTracker.track_event(
                db=db,
                user_id=user_id,
                event_type=CostEventType.TTS_CHARACTERS,
                quantity=character_count,
                unit_cost=unit_cost,
                provider=CostProvider.GOOGLE if self.provider.get_provider_name() == "google" else CostProvider.INTERNAL,
                document_id=document_id,
                job_id=job_id,
                voice_id=voice_id,
                success=True,
                attempt_number=attempt,
                metadata={
                    "provider": self.provider.get_provider_name(),
                    "voice_id": voice_id,
                    "language_code": language_code,
                    "audio_size_bytes": len(audio_bytes),
                    "duration_seconds": duration,
                }
            )

            # Emit metrics
            tts_requests_total.labels(
                provider=self.provider.get_provider_name(),
                status="success"
            ).inc()
            
            tts_characters_total.labels(
                provider=self.provider.get_provider_name()
            ).inc(character_count)
            
            tts_cost_usd_total.labels(
                provider=self.provider.get_provider_name()
            ).inc(estimated_cost)
            
            tts_latency_seconds.labels(
                provider=self.provider.get_provider_name()
            ).observe(duration)
            
            logger.info(
                f"TTS synthesis completed successfully",
                extra={
                    "user_id": str(user_id),
                    "character_count": character_count,
                    "cost_usd": estimated_cost,
                    "audio_size_bytes": len(audio_bytes),
                    "duration_seconds": duration,
                }
            )
            
            return audio_bytes
            
        except TTSProviderError as e:
            # Calculate duration even on failure
            duration = time.time() - start_time
            
            # Emit failure metrics
            tts_requests_total.labels(
                provider=self.provider.get_provider_name(),
                status="failed"
            ).inc()
            
            tts_failures_total.labels(
                provider=self.provider.get_provider_name(),
                failure_reason=e.__class__.__name__
            ).inc()
            
            logger.error(
                f"TTS synthesis failed: {str(e)}",
                extra={
                    "user_id": str(user_id),
                    "character_count": character_count,
                    "error": str(e),
                    "error_type": e.__class__.__name__,
                    "duration_seconds": duration,
                },
                exc_info=True
            )

            # The attempt that finally gave up is still work the provider was
            # asked to do — keep it countable before propagating.
            await self._record_failed_attempt(
                db, user_id, character_count, unit_cost, voice_id,
                e, attempt, document_id, job_id,
            )

            # Re-raise for caller to handle
            raise

    async def _record_failed_attempt(
        self,
        db: AsyncSession,
        user_id: UUID,
        character_count: int,
        unit_cost: float,
        voice_id: Optional[str],
        error: Exception,
        attempt: int,
        document_id: Optional[UUID],
        job_id: Optional[UUID],
    ) -> None:
        """
        Persist a zero-cost record of a failed provider attempt.

        Zero-cost is the honest value: Google does not bill a failed request,
        and we have no invoice to read.  The row exists so failed work is
        countable — characters attempted, voice, reason — without pretending
        money changed hands.

        A ledger failure must never mask the TTS error the caller is about to
        see, so it is logged loudly and swallowed here rather than raised.
        """
        try:
            await CostTracker.track_event(
                db=db,
                user_id=user_id,
                event_type=CostEventType.TTS_CHARACTERS,
                quantity=character_count,
                unit_cost=unit_cost,
                provider=CostProvider.GOOGLE if self.provider.get_provider_name() == "google" else CostProvider.INTERNAL,
                document_id=document_id,
                job_id=job_id,
                voice_id=voice_id,
                success=False,
                failure_reason=error.__class__.__name__,
                attempt_number=attempt,
                metadata={"error": str(error)[:500]},
            )
            logger.warning(
                "[SONORO] failed_job_cost_recorded user_id=%s job_id=%s attempt=%d "
                "chars=%d voice=%s reason=%s",
                user_id, job_id, attempt, character_count, voice_id,
                error.__class__.__name__,
            )
        except Exception as ledger_error:
            logger.error(
                "[SONORO] cost_event_write_failed user_id=%s job_id=%s attempt=%d error=%s",
                user_id, job_id, attempt, str(ledger_error), exc_info=True,
            )


    def estimate_cost(self, character_count: int) -> float:
        """
        Estimate cost without performing synthesis.
        
        Args:
            character_count: Number of characters
            
        Returns:
            Estimated cost in USD
        """
        return self.provider.estimate_cost(character_count)
    
    def get_provider_name(self) -> str:
        """Get the name of the current provider."""
        return self.provider.get_provider_name()

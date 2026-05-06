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

import logging
import time
from typing import Optional
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.financial.cost.cost_tracker import CostTracker
from app.financial.cost.cost_enums import CostEventType, CostProvider
from app.services.tts.base import TTSProvider, TTSProviderError
from app.services.tts.google_provider import GoogleTTSProvider
from app.financial.financial_metrics import (
    cost_events_total,
)

logger = logging.getLogger(__name__)


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
        
        # Estimate cost
        estimated_cost = self.provider.estimate_cost(character_count)
        
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
        
        try:
            # Call provider
            audio_bytes = await self.provider.synthesize(
                text=text,
                voice_id=voice_id,
                language_code=language_code,
            )
            
            # Calculate actual duration
            duration = time.time() - start_time
            
            # Record cost event using existing cost governance
            await CostTracker.track_event(
                db=db,
                user_id=user_id,
                event_type=CostEventType.TTS_CHARACTERS,
                quantity=character_count,
                unit_cost=self.provider.estimate_cost(1),  # Cost per character
                provider=CostProvider.GOOGLE if self.provider.get_provider_name() == "google" else CostProvider.INTERNAL,
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
            
            # Re-raise for caller to handle
            raise
    
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

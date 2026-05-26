"""
Preflight Document Analysis Service
=====================================
Lightweight pre-conversion analysis returned to the frontend BEFORE a
processing job is created.  All computations are pure math or fast DB reads —
no TTS calls, no ffmpeg, no storage uploads.

Usage:
    result = await PreflightService.analyze(document=doc, user=user, db=session)
"""

import logging
from dataclasses import dataclass, field
from typing import Optional
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.financial.quota.quota_limits import PlanTier, PLAN_QUOTAS, get_plan_limits
from app.financial.quota.quota_service import QuotaService

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Conservative speaking rate for Google Neural2 voices (chars/second).
# Measured empirically: ~150 wpm × 5.1 chars/word ÷ 60 ≈ 12.75 → round to 14.
_TTS_CHARS_PER_SECOND = 14

# Same constant used in processing.py for pre-counting chunks.
_TTS_CHUNK_SIZE = 4_500

# Rough API round-trip for one TTS synthesis call.
_TTS_SECONDS_PER_CHUNK = 2

# Overhead: structure analysis + chapter detection + ffmpeg assembly + upload.
_PIPELINE_OVERHEAD_SECONDS = 120

# ---------------------------------------------------------------------------
# Display maps  (single source of truth; also exported for detector.py parity)
# ---------------------------------------------------------------------------

LANGUAGE_DISPLAY_MAP: dict[str, str] = {
    "en":    "English",
    "es":    "Spanish",
    "fr":    "French",
    "pt":    "Portuguese",
    "de":    "German",
    "it":    "Italian",
    "nl":    "Dutch",
    "pl":    "Polish",
    "ru":    "Russian",
    "ja":    "Japanese",
    "ko":    "Korean",
    "zh-cn": "Chinese (Simplified)",
    "zh-tw": "Chinese (Traditional)",
}

# Maps voice_id → human-readable label shown in the UI.
VOICE_DISPLAY_MAP: dict[str, str] = {
    "en-US-Neural2-A":   "English (US) · Neural2",
    "es-US-Neural2-A":   "Spanish (US) · Neural2",
    "fr-FR-Neural2-A":   "French · Neural2",
    "pt-BR-Neural2-A":   "Portuguese (BR) · Neural2",
    "de-DE-Neural2-A":   "German · Neural2",
    "it-IT-Neural2-A":   "Italian · Neural2",
    "nl-NL-Neural2-A":   "Dutch · Neural2",
    "pl-PL-Standard-A":  "Polish · Standard",
    "ru-RU-Standard-A":  "Russian · Standard",
    "ja-JP-Neural2-B":   "Japanese · Neural2",
    "ko-KR-Neural2-A":   "Korean · Neural2",
    "cmn-CN-Wavenet-A":  "Chinese (CN) · WaveNet",
    "cmn-TW-Wavenet-A":  "Chinese (TW) · WaveNet",
}

PLAN_DISPLAY_MAP: dict[str, str] = {
    "FREE":       "Free",
    "BASIC":      "Basic",
    "PRO":        "Pro",
    "ENTERPRISE": "Enterprise",
}


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

@dataclass
class AvailableVoice:
    voice_id: str
    display_name: str


@dataclass
class PreflightAnalysis:
    language: str               # ISO 639-1 code
    language_name: str          # "Spanish"
    voice_id: str               # "es-US-Neural2-A"
    voice_display_name: str     # "Spanish (US) · Neural2"
    available_voices: list      # list[AvailableVoice]
    estimated_characters: int
    estimated_chapters: int
    estimated_duration_seconds: int
    estimated_processing_minutes: float
    fits_current_plan: bool
    quota_exceeded: bool
    chars_limit: int
    chars_used: int
    chars_remaining_before: int
    chars_remaining_after: int  # can be negative if over quota
    plan_tier: str
    plan_display_name: str


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------

class PreflightService:
    """Pure estimation logic — no I/O except a single quota DB read."""

    # -- Public entry point --------------------------------------------------

    @staticmethod
    async def analyze(
        document,           # Document ORM object
        user,               # User ORM object
        db: AsyncSession,
    ) -> PreflightAnalysis:
        """
        Run lightweight preflight analysis for a freshly uploaded document.

        Reads: document fields already populated by _extract_metadata
               (character_estimate, page_count, language_detected) + quota row.
        Writes: nothing.
        """
        chars = document.character_estimate or 0
        pages = document.page_count or 0
        language = document.language_detected or "en"

        # Resolve voice
        from app.services.language.detector import VOICE_MAP  # deferred: avoids circular
        language_code, voice_id = VOICE_MAP.get(language, ("en-US", "en-US-Neural2-A"))
        language_name = LANGUAGE_DISPLAY_MAP.get(language, language.upper())
        voice_display = VOICE_DISPLAY_MAP.get(voice_id, voice_id)

        # For now one voice per language; the list gives the UI a dropdown
        # affordance without requiring a backend change when more voices ship.
        available_voices = [AvailableVoice(voice_id=voice_id, display_name=voice_display)]

        # Estimations
        estimated_chapters = PreflightService._estimate_chapters(pages)
        estimated_duration = PreflightService._estimate_duration_seconds(chars)
        estimated_processing = PreflightService._estimate_processing_minutes(chars)

        # Quota
        plan_tier_str = user.plan_tier if user.plan_tier else "FREE"
        plan_tier = PlanTier(plan_tier_str)
        limits = get_plan_limits(plan_tier)
        quota = await QuotaService.get_or_create_quota(db, user.id)

        chars_used = quota.characters_used
        chars_limit = limits.monthly_char_limit
        chars_remaining_before = max(0, chars_limit - chars_used)
        chars_remaining_after = chars_remaining_before - chars
        fits_current_plan = chars_remaining_after >= 0
        quota_exceeded = not fits_current_plan

        logger.info(
            "[SONORO] preflight_analysis doc_id=%s language=%s chars=%d duration_s=%d "
            "chapters=%d fits_plan=%s",
            document.id, language, chars, estimated_duration,
            estimated_chapters, fits_current_plan,
        )

        return PreflightAnalysis(
            language=language,
            language_name=language_name,
            voice_id=voice_id,
            voice_display_name=voice_display,
            available_voices=available_voices,
            estimated_characters=chars,
            estimated_chapters=estimated_chapters,
            estimated_duration_seconds=estimated_duration,
            estimated_processing_minutes=estimated_processing,
            fits_current_plan=fits_current_plan,
            quota_exceeded=quota_exceeded,
            chars_limit=chars_limit,
            chars_used=chars_used,
            chars_remaining_before=chars_remaining_before,
            chars_remaining_after=chars_remaining_after,
            plan_tier=plan_tier_str,
            plan_display_name=PLAN_DISPLAY_MAP.get(plan_tier_str, plan_tier_str),
        )

    # -- Pure estimation helpers (also used by tests) -----------------------

    @staticmethod
    def _estimate_chapters(page_count: int | None) -> int:
        """Heuristic: one chapter per N pages based on book length."""
        if not page_count or page_count < 1:
            return 1
        if page_count <= 10:
            return 1
        if page_count <= 50:
            return max(1, page_count // 15)
        if page_count <= 200:
            return max(1, page_count // 25)
        return max(1, page_count // 35)

    @staticmethod
    def _estimate_duration_seconds(chars: int) -> int:
        """Estimate audiobook duration from character count."""
        if chars <= 0:
            return 0
        return max(1, int(chars / _TTS_CHARS_PER_SECOND))

    @staticmethod
    def _estimate_processing_minutes(chars: int) -> float:
        """Rough end-to-end processing time estimate."""
        if chars <= 0:
            return round(_PIPELINE_OVERHEAD_SECONDS / 60, 1)
        chunks = max(1, chars // _TTS_CHUNK_SIZE)
        total_seconds = chunks * _TTS_SECONDS_PER_CHUNK + _PIPELINE_OVERHEAD_SECONDS
        return round(total_seconds / 60, 1)

"""
Language detection and TTS voice mapping.

Detects the language of a document from extracted text and returns the
appropriate Google Cloud TTS voice and language code.
"""

import logging
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)

# Characters sampled for detection — enough for reliable results without being
# excessive. langdetect is accurate after ~200 chars; 3000 is a safe upper bound.
_DETECTION_SAMPLE_SIZE = 3000

# Mapping: ISO 639-1 code → (google_language_code, google_voice_name)
# Add entries here to expand language support.
VOICE_MAP: dict[str, tuple[str, str]] = {
    "en": ("en-US", "en-US-Neural2-A"),
    "es": ("es-US", "es-US-Neural2-A"),
    "fr": ("fr-FR", "fr-FR-Neural2-A"),
    "pt": ("pt-BR", "pt-BR-Neural2-A"),
    "de": ("de-DE", "de-DE-Neural2-A"),
    "it": ("it-IT", "it-IT-Neural2-A"),
    "nl": ("nl-NL", "nl-NL-Neural2-A"),
    "pl": ("pl-PL", "pl-PL-Standard-A"),
    "ru": ("ru-RU", "ru-RU-Standard-A"),
    "ja": ("ja-JP", "ja-JP-Neural2-B"),
    "ko": ("ko-KR", "ko-KR-Neural2-A"),
    "zh-cn": ("cmn-CN", "cmn-CN-Wavenet-A"),
    "zh-tw": ("cmn-TW", "cmn-TW-Wavenet-A"),
}

_DEFAULT_LANGUAGE = "en"
_DEFAULT_LANGUAGE_CODE = "en-US"
_DEFAULT_VOICE = "en-US-Neural2-A"


@dataclass
class DetectionResult:
    language: str           # ISO 639-1 code, e.g. "es"
    confidence: Optional[float]  # 0.0–1.0 or None if detection failed
    language_code: str      # Google TTS language code, e.g. "es-US"
    voice_id: str           # Google TTS voice name, e.g. "es-US-Neural2-A"


def detect_language(text: str, document_id: str = "") -> DetectionResult:
    """Detect language from text and return the matching TTS voice.

    Sampling is limited to _DETECTION_SAMPLE_SIZE chars for performance.
    On any failure (import error, detection error, ambiguous result) the function
    logs a warning and returns the English fallback instead of raising.
    """
    sample = text[:_DETECTION_SAMPLE_SIZE].strip()

    if len(sample) < 20:
        logger.warning(
            "[SONORO] language_detection_skipped document_id=%s reason=text_too_short",
            document_id,
        )
        return _english_fallback(document_id, reason="text_too_short")

    try:
        from langdetect import detect_langs  # deferred: keeps import errors local

        results = detect_langs(sample)
        if not results:
            return _english_fallback(document_id, reason="no_results")

        top = results[0]
        lang: str = top.lang   # e.g. "es", "en", "zh-cn"
        confidence: float = round(top.prob, 4)

        logger.info(
            "[SONORO] language_detected document_id=%s language=%s confidence=%.4f",
            document_id, lang, confidence,
        )

        language_code, voice_id = VOICE_MAP.get(
            lang,
            # Unknown language → warn and fall back to English voice
            (_DEFAULT_LANGUAGE_CODE, _DEFAULT_VOICE),
        )

        if lang not in VOICE_MAP:
            logger.warning(
                "[SONORO] tts_voice_unmapped document_id=%s language=%s — using English fallback",
                document_id, lang,
            )

        logger.info(
            "[SONORO] tts_voice_selected document_id=%s language=%s voice=%s language_code=%s",
            document_id, lang, voice_id, language_code,
        )

        return DetectionResult(
            language=lang,
            confidence=confidence,
            language_code=language_code,
            voice_id=voice_id,
        )

    except Exception as exc:
        logger.warning(
            "[SONORO] language_detection_failed document_id=%s error=%s — falling back to English",
            document_id, exc,
        )
        return _english_fallback(document_id, reason="exception")


def _english_fallback(document_id: str, reason: str) -> DetectionResult:
    logger.warning(
        "[SONORO] language_detection_fallback document_id=%s reason=%s default=en",
        document_id, reason,
    )
    return DetectionResult(
        language=_DEFAULT_LANGUAGE,
        confidence=None,
        language_code=_DEFAULT_LANGUAGE_CODE,
        voice_id=_DEFAULT_VOICE,
    )

"""
Unit tests for language detection and TTS voice mapping.

Tests cover:
- Spanish text → es, es-US voice
- English text → en, en-US voice
- Detection failure → English fallback with confidence=None
- Text too short → English fallback
- Unmapped language → English voice fallback
"""

from unittest.mock import patch, MagicMock

import pytest

from app.services.language.detector import detect_language, VOICE_MAP


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

_SPANISH_TEXT = (
    "El fútbol es el deporte más popular del mundo. "
    "Millones de aficionados siguen los partidos de sus equipos favoritos. "
    "Los jugadores entrenan durante horas para alcanzar la perfección. "
    "La Copa del Mundo es el torneo más importante del fútbol. "
    "España ha ganado varios torneos internacionales a lo largo de los años. "
    "Los aficionados llenan los estadios para apoyar a sus equipos. "
    "El deporte une a personas de todas las culturas y naciones del planeta. "
) * 5  # ~700 chars, well above minimum

_ENGLISH_TEXT = (
    "The history of computing began in the nineteenth century with Charles Babbage. "
    "Alan Turing laid the theoretical foundations for modern computer science. "
    "Today, computers are essential tools in every field of human endeavor. "
    "Software engineering has grown into one of the most important disciplines. "
    "Machine learning is transforming the way we analyze and interpret data. "
) * 5  # ~500 chars


def _mock_detect_langs(text):
    """Build a minimal langdetect result mock."""
    class _Result:
        def __init__(self, lang, prob):
            self.lang = lang
            self.prob = prob
    return [_Result("es", 0.9999)]


# ---------------------------------------------------------------------------
# Happy-path tests
# ---------------------------------------------------------------------------

def test_spanish_text_detected_and_mapped():
    result = detect_language(_SPANISH_TEXT, document_id="test-doc-es")

    assert result.language == "es"
    assert result.confidence is not None
    assert result.confidence > 0.8
    assert result.language_code == "es-US"
    assert result.voice_id == "es-US-Neural2-A"


def test_english_text_detected_and_mapped():
    result = detect_language(_ENGLISH_TEXT, document_id="test-doc-en")

    assert result.language == "en"
    assert result.confidence is not None
    assert result.confidence > 0.8
    assert result.language_code == "en-US"
    assert result.voice_id == "en-US-Neural2-A"


# ---------------------------------------------------------------------------
# Fallback tests
# ---------------------------------------------------------------------------

def test_text_too_short_falls_back_to_english():
    result = detect_language("Hi", document_id="test-short")

    assert result.language == "en"
    assert result.confidence is None
    assert result.voice_id == "en-US-Neural2-A"


def test_detection_exception_falls_back_to_english():
    with patch("app.services.language.detector.detect_language") as _:
        # Simulate langdetect raising inside detect_language by patching the import
        pass

    # Patch detect_langs to raise
    with patch.dict("sys.modules", {"langdetect": MagicMock()}):
        import sys
        sys.modules["langdetect"].detect_langs.side_effect = RuntimeError("detector crash")

        result = detect_language(_ENGLISH_TEXT, document_id="test-fail")

    # After exception: language stays en, confidence None
    assert result.language == "en"
    assert result.confidence is None
    assert result.voice_id == "en-US-Neural2-A"


def test_unmapped_language_falls_back_to_english_voice():
    """A language detected but not in VOICE_MAP must still return a valid English voice."""
    with patch("langdetect.detect_langs") as mock_detect:
        mock_result = MagicMock()
        mock_result.lang = "sw"   # Swahili — not in VOICE_MAP
        mock_result.prob = 0.95
        mock_detect.return_value = [mock_result]

        result = detect_language(_ENGLISH_TEXT * 2, document_id="test-unmapped")

    assert result.language == "sw"
    # Must still return a usable voice, not crash
    assert result.voice_id == "en-US-Neural2-A"
    assert result.language_code == "en-US"
    assert result.confidence == 0.95


# ---------------------------------------------------------------------------
# Voice map completeness
# ---------------------------------------------------------------------------

def test_voice_map_has_spanish_and_english():
    assert "en" in VOICE_MAP
    assert "es" in VOICE_MAP
    lang_code, voice = VOICE_MAP["es"]
    assert lang_code.startswith("es-")
    assert "Neural2" in voice or "Wavenet" in voice or "Standard" in voice

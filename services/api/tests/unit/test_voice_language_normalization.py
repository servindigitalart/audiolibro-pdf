"""
Unit Tests: Voice Preview Language Code Normalization
======================================================
Regression tests for the bug where Google TTS received language_code='es'
with voice_id='es-US-Neural2-A'.  Google requires the full BCP-47 code
('es-US') and rejects generic ISO-639-1 codes ('es') for region-specific voices.

No network calls, no DB, no auth — pure logic tests.
"""
import pytest

from app.routers.voices import _derive_language_code

pytestmark = pytest.mark.unit


# ── _derive_language_code ─────────────────────────────────────────────────────

class TestDeriveLanguageCode:

    def test_spanish_us_voice(self):
        assert _derive_language_code("es-US-Neural2-A", "en-US") == "es-US"

    def test_english_us_voice(self):
        assert _derive_language_code("en-US-Neural2-A", "en-US") == "en-US"

    def test_english_gb_voice(self):
        assert _derive_language_code("en-GB-Neural2-B", "en-US") == "en-GB"

    def test_french_fr_voice(self):
        assert _derive_language_code("fr-FR-Neural2-A", "en-US") == "fr-FR"

    def test_portuguese_br_voice(self):
        assert _derive_language_code("pt-BR-Neural2-A", "en-US") == "pt-BR"

    def test_german_de_voice(self):
        assert _derive_language_code("de-DE-Neural2-A", "en-US") == "de-DE"

    def test_japanese_voice(self):
        assert _derive_language_code("ja-JP-Neural2-B", "en-US") == "ja-JP"

    def test_korean_voice(self):
        assert _derive_language_code("ko-KR-Neural2-A", "en-US") == "ko-KR"

    def test_invalid_voice_returns_fallback(self):
        """Unknown format should return the provided fallback unchanged."""
        assert _derive_language_code("invalid-voice", "en-US") == "en-US"

    def test_empty_voice_returns_fallback(self):
        assert _derive_language_code("", "en-US") == "en-US"

    def test_single_segment_returns_fallback(self):
        assert _derive_language_code("English", "en-US") == "en-US"

    def test_generic_iso_input_is_overridden_by_voice(self):
        """
        If the caller passes language_code='es' (generic ISO code) but the
        voice is 'es-US-Neural2-A', the function must return 'es-US'.
        This is the exact scenario that caused the Spanish preview failure.
        """
        result = _derive_language_code("es-US-Neural2-A", "es")
        assert result == "es-US", (
            f"Expected 'es-US' but got '{result}'. "
            "Google TTS rejects 'es' as language_code for es-US voices."
        )


# ── Integration-level: language code consistency with preview text ────────────

class TestPreviewTextLanguageMapping:
    """Verify that the derived language code maps to a valid preview text."""

    def test_spanish_voice_gets_spanish_preview_text(self):
        """After deriving 'es-US', lang_short='es' → Spanish preview text is used."""
        from app.routers.voices import _PREVIEW_TEXTS, _derive_language_code

        lang_code = _derive_language_code("es-US-Neural2-A", "en-US")
        lang_short = lang_code[:2].lower()
        assert lang_short in _PREVIEW_TEXTS, (
            f"No preview text for lang_short='{lang_short}' derived from es-US-Neural2-A"
        )
        assert "Bienvenido" in _PREVIEW_TEXTS[lang_short]

    def test_english_voice_gets_english_preview_text(self):
        from app.routers.voices import _PREVIEW_TEXTS, _derive_language_code

        lang_code = _derive_language_code("en-US-Neural2-A", "en-US")
        lang_short = lang_code[:2].lower()
        assert lang_short in _PREVIEW_TEXTS
        assert "Welcome" in _PREVIEW_TEXTS[lang_short]

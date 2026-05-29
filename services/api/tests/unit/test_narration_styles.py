"""
Unit Tests: Narration Style System
====================================
Tests for:
  - get_style_params() returns correct rate/pitch per style
  - Unknown / None style falls back to DEFAULT_PARAMS
  - Values are clamped to Google TTS safe ranges
  - Google provider receives non-default speaking_rate/pitch
  - Process endpoint accepts narration_style in body
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from app.services.tts.narration_style import (
    get_style_params,
    STYLE_MAP,
    DEFAULT_PARAMS,
    StyleParams,
)

pytestmark = pytest.mark.unit


# ── Style mapping — expected values ───────────────────────────────────────────

@pytest.mark.parametrize("style,expected_rate,expected_pitch", [
    ("calm",         0.90, -1.0),
    ("storytelling", 0.97,  0.5),
    ("documentary",  0.94, -1.5),
    ("podcast",      1.04,  0.0),
    ("educational",  0.92,  0.0),
])
def test_style_returns_expected_params(style, expected_rate, expected_pitch):
    params = get_style_params(style)
    assert params.speaking_rate == pytest.approx(expected_rate)
    assert params.pitch         == pytest.approx(expected_pitch)


def test_all_five_styles_covered():
    required = {"calm", "storytelling", "documentary", "podcast", "educational"}
    assert required == set(STYLE_MAP.keys())


# ── Fallback to default ────────────────────────────────────────────────────────

def test_none_style_returns_default():
    params = get_style_params(None)
    assert params == DEFAULT_PARAMS
    assert params.speaking_rate == pytest.approx(1.0)
    assert params.pitch         == pytest.approx(0.0)


def test_empty_string_returns_default():
    assert get_style_params("") == DEFAULT_PARAMS


def test_unknown_style_returns_default():
    assert get_style_params("asmr") == DEFAULT_PARAMS


def test_case_insensitive():
    assert get_style_params("CALM") == get_style_params("calm")
    assert get_style_params("Podcast") == get_style_params("podcast")


# ── Clamping ───────────────────────────────────────────────────────────────────

def test_all_mapped_rates_within_google_range():
    for style, params in STYLE_MAP.items():
        assert 0.25 <= params.speaking_rate <= 4.0, f"{style} rate out of range"


def test_all_mapped_pitches_within_google_range():
    for style, params in STYLE_MAP.items():
        assert -20.0 <= params.pitch <= 20.0, f"{style} pitch out of range"


def test_out_of_range_rate_is_clamped():
    # Patch STYLE_MAP to inject an extreme value and confirm clamping
    with patch.dict("app.services.tts.narration_style.STYLE_MAP", {
        "extreme": StyleParams(speaking_rate=999.0, pitch=0.0)
    }):
        params = get_style_params("extreme")
        assert params.speaking_rate == pytest.approx(4.0)


def test_out_of_range_pitch_is_clamped():
    with patch.dict("app.services.tts.narration_style.STYLE_MAP", {
        "extreme": StyleParams(speaking_rate=1.0, pitch=-999.0)
    }):
        params = get_style_params("extreme")
        assert params.pitch == pytest.approx(-20.0)


# ── Google provider receives non-default params ────────────────────────────────

async def test_google_provider_receives_style_params():
    """Verify that speaking_rate and pitch flow into the AudioConfig."""
    from app.services.tts.google_provider import GoogleTTSProvider

    fake_response = MagicMock()
    fake_response.audio_content = b"fake_mp3"

    provider = GoogleTTSProvider.__new__(GoogleTTSProvider)
    provider.client = MagicMock()
    provider.client.synthesize_speech.return_value = fake_response

    captured: dict = {}

    def _capture(input, voice, audio_config):
        captured["speaking_rate"] = audio_config.speaking_rate
        captured["pitch"]         = audio_config.pitch
        return fake_response

    provider.client.synthesize_speech.side_effect = _capture

    result = await provider.synthesize(
        text="Hello world",
        voice_id="en-US-Neural2-A",
        language_code="en-US",
        speaking_rate=0.90,
        pitch=-1.0,
    )

    assert result == b"fake_mp3"
    assert captured["speaking_rate"] == pytest.approx(0.90)
    assert captured["pitch"]         == pytest.approx(-1.0)


async def test_google_provider_default_params_unchanged():
    """Default call (no style) still uses 1.0 / 0.0."""
    from app.services.tts.google_provider import GoogleTTSProvider

    fake_response = MagicMock()
    fake_response.audio_content = b"mp3"

    provider = GoogleTTSProvider.__new__(GoogleTTSProvider)
    provider.client = MagicMock()

    captured: dict = {}

    def _capture(input, voice, audio_config):
        captured["speaking_rate"] = audio_config.speaking_rate
        captured["pitch"]         = audio_config.pitch
        return fake_response

    provider.client.synthesize_speech.side_effect = _capture

    await provider.synthesize(
        text="Hello",
        voice_id="en-US-Neural2-A",
        language_code="en-US",
    )

    assert captured["speaking_rate"] == pytest.approx(1.0)
    assert captured["pitch"]         == pytest.approx(0.0)


# ── ProcessDocumentRequest accepts narration_style ────────────────────────────

def test_process_request_accepts_narration_style():
    from app.schemas.processing import ProcessDocumentRequest
    req = ProcessDocumentRequest(narration_style="calm", voice_id="en-US-Neural2-C")
    assert req.narration_style == "calm"
    assert req.voice_id        == "en-US-Neural2-C"


def test_process_request_defaults_to_none():
    from app.schemas.processing import ProcessDocumentRequest
    req = ProcessDocumentRequest()
    assert req.narration_style is None
    assert req.voice_id        is None


# ── Backward compatibility: no style → default TTS params ─────────────────────

async def test_tts_service_uses_default_params_without_style():
    from app.services.tts.tts_service import TTSService
    from app.services.tts.base import TTSProvider

    class FakeProvider(TTSProvider):
        def __init__(self): self.calls = []
        async def synthesize(self, text, voice_id, language_code,
                             speaking_rate=1.0, pitch=0.0) -> bytes:
            self.calls.append({"speaking_rate": speaking_rate, "pitch": pitch})
            return b"audio"
        def estimate_cost(self, n): return 0.0
        def get_provider_name(self): return "fake"

    fake = FakeProvider()
    service = TTSService(provider=fake)
    db = AsyncMock()

    await service.synthesize_text(
        db=db,
        user_id=uuid4(),
        text="Hello",
        voice_id="v1",
        language_code="en-US",
        # no speaking_rate / pitch → should default
    )

    assert fake.calls[0]["speaking_rate"] == pytest.approx(1.0)
    assert fake.calls[0]["pitch"]         == pytest.approx(0.0)


async def test_tts_service_forwards_style_params():
    from app.services.tts.tts_service import TTSService
    from app.services.tts.base import TTSProvider

    class FakeProvider(TTSProvider):
        def __init__(self): self.calls = []
        async def synthesize(self, text, voice_id, language_code,
                             speaking_rate=1.0, pitch=0.0) -> bytes:
            self.calls.append({"speaking_rate": speaking_rate, "pitch": pitch})
            return b"audio"
        def estimate_cost(self, n): return 0.0
        def get_provider_name(self): return "fake"

    fake = FakeProvider()
    service = TTSService(provider=fake)
    db = AsyncMock()

    await service.synthesize_text(
        db=db,
        user_id=uuid4(),
        text="Hello",
        voice_id="v1",
        language_code="en-US",
        speaking_rate=0.94,
        pitch=-1.5,
    )

    assert fake.calls[0]["speaking_rate"] == pytest.approx(0.94)
    assert fake.calls[0]["pitch"]         == pytest.approx(-1.5)

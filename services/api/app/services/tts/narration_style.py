"""
Narration Style Parameters
===========================
Maps narration style names to Google TTS AudioConfig parameters.

Google TTS safe ranges:
  speaking_rate: 0.25–4.0  (1.0 = normal speed)
  pitch:        -20.0–20.0  semitones (0.0 = normal pitch)
"""

from dataclasses import dataclass
from typing import Optional

_RATE_MIN = 0.25
_RATE_MAX = 4.0
_PITCH_MIN = -20.0
_PITCH_MAX = 20.0


@dataclass(frozen=True)
class StyleParams:
    speaking_rate: float
    pitch: float


# Centralized style → TTS parameter mapping.
# All values stay within safe Google TTS ranges.
STYLE_MAP: dict[str, StyleParams] = {
    "calm":         StyleParams(speaking_rate=0.90, pitch=-1.0),
    "storytelling": StyleParams(speaking_rate=0.97, pitch=0.5),
    "documentary":  StyleParams(speaking_rate=0.94, pitch=-1.5),
    "podcast":      StyleParams(speaking_rate=1.04, pitch=0.0),
    "educational":  StyleParams(speaking_rate=0.92, pitch=0.0),
}

DEFAULT_PARAMS = StyleParams(speaking_rate=1.0, pitch=0.0)


def get_style_params(narration_style: Optional[str]) -> StyleParams:
    """
    Return clamped TTS parameters for *narration_style*.
    Unknown or absent styles return DEFAULT_PARAMS.
    """
    if not narration_style:
        return DEFAULT_PARAMS

    params = STYLE_MAP.get(narration_style.lower(), DEFAULT_PARAMS)

    rate  = max(_RATE_MIN,  min(_RATE_MAX,  params.speaking_rate))
    pitch = max(_PITCH_MIN, min(_PITCH_MAX, params.pitch))
    return StyleParams(speaking_rate=rate, pitch=pitch)

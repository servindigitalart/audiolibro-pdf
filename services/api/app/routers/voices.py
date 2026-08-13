"""
Voice Preview Router
====================
Lightweight endpoint for generating short TTS preview samples.

Each voice+language+style combination is synthesized once per server process
and the audio bytes are cached in memory. Subsequent calls skip TTS
entirely and serve the cached bytes directly.

Intentionally bypasses Celery, quota tracking, and cost events:
previews use a fixed ~90-char text that costs <$0.002 per voice,
are globally cached, and are not attributed to user quota.

That bypass is only defensible while the number of *distinct* paid calls a
caller can force stays small, which is what the two guards below protect
(Phase 0E / audit 0.9):

  - the route carries the API rate-limit tier, so previews are bounded per user
    like any other authenticated endpoint;
  - the cache is keyed on the RESOLVED style parameters and bounded by an LRU,
    so junk `narration_style` values can neither mint unlimited provider calls
    nor grow the process heap without limit.
"""

import asyncio
from collections import OrderedDict
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import Response

from app.core.logging_config import get_logger
from app.core.auth_dependencies import get_current_active_user
from app.db.models.user import User
from app.financial.rate_limit.dependencies import rate_limit
from app.financial.rate_limit.rate_limit_service import RateLimitTier
from app.services.tts.google_provider import GoogleTTSProvider
from app.services.tts.base import TTSProviderError
from app.services.tts.narration_style import StyleParams, get_style_params

logger = get_logger(__name__)

router = APIRouter(prefix="/api/v1/voices", tags=["voices"])

# Short preview text per language (≤100 chars → cheap TTS call)
_PREVIEW_TEXTS: dict[str, str] = {
    "en": "Welcome to your personal audiobook. Experience the joy of reading through the art of sound.",
    "es": "Bienvenido a tu audiolibro personal. Descubre el placer de la lectura a través del sonido.",
    "fr": "Bienvenue dans votre livre audio. Découvrez le plaisir de la lecture grâce à la magie du son.",
    "de": "Willkommen in Ihrem Hörbuch. Erleben Sie die Freude am Lesen durch die Kunst des Klangs.",
    "pt": "Bem-vindo ao seu audiolivro. Experiencie a alegria da leitura através da arte do som.",
    "it": "Benvenuto nel tuo audiolibro. Vivi la gioia della lettura attraverso l'arte del suono.",
    "ja": "あなたのオーディオブックへようこそ。音の芸術を通じて読書の喜びを体験してください。",
    "zh": "欢迎来到您的个人有声书。通过声音的艺术体验阅读的乐趣。",
    "ko": "개인 오디오북에 오신 것을 환영합니다. 소리의 예술을 통해 독서의 기쁨을 경험해 보세요.",
    "ru": "Добро пожаловать в ваш личный аудиокнигу. Откройте радость чтения через искусство звука.",
}
_DEFAULT_PREVIEW_TEXT = _PREVIEW_TEXTS["en"]

# Global cache: resolved-parameter key → MP3 bytes.
#
# Bounded LRU rather than a plain dict.  Keying on the resolved StyleParams (see
# _cache_key) already collapses every unknown narration_style onto the default
# entry, but voice_id remains caller-supplied and Google publishes ~1600 voices,
# so the dict still needs a ceiling.  A preview is ~30-90 KB, so 128 entries is
# roughly 4-12 MB — small enough to keep per worker process, large enough that
# the voices real users pick stay warm.
_CACHE_MAX_ENTRIES = 128
_cache: "OrderedDict[str, bytes]" = OrderedDict()
_cache_lock = asyncio.Lock()


def _cache_key(voice_id: str, language_code: str, params: StyleParams) -> str:
    """
    Build the cache key from the *resolved* synthesis parameters.

    The raw narration_style string must never reach the key: get_style_params
    maps every unrecognised style to DEFAULT_PARAMS, so `?narration_style=foo`,
    `=bar` and `=baz` all synthesize byte-identical audio.  Keying on the raw
    string gave each of them its own miss, its own paid provider call and its
    own cache entry — unbounded work from unbounded input.  Two requests that
    would produce the same audio now produce the same key.
    """
    return f"{voice_id}:{language_code}:{params.speaking_rate}:{params.pitch}"


def _derive_language_code(voice_id: str, fallback: str) -> str:
    """
    Derive the BCP-47 language code from a Google TTS voice_id.

    Google voice IDs follow the pattern "{lang}-{region}-{type}-{letter}",
    e.g. "es-US-Neural2-A" → "es-US", "en-GB-Neural2-A" → "en-GB".
    Sending the generic ISO-639-1 code ("es") instead of the full BCP-47 code
    ("es-US") causes Google TTS to reject the request with a 400 error.
    """
    parts = voice_id.split("-")
    if len(parts) >= 2 and len(parts[0]) == 2 and len(parts[1]) == 2:
        return f"{parts[0]}-{parts[1]}"
    return fallback


@router.get(
    "/preview",
    # Previews call a paid provider outside the cost guard and the cost ledger,
    # so the rate limit is the only ceiling on how often that can happen.
    # Declared on the route, not in the body, so it cannot be skipped.
    dependencies=[Depends(rate_limit(RateLimitTier.API))],
)
async def preview_voice(
    voice_id:        str,
    language_code:   str = "en-US",
    narration_style: Optional[str] = None,
    current_user:    User = Depends(get_current_active_user),
) -> Response:
    """
    Stream a short TTS audio sample for the given voice.

    Returns raw MP3 bytes so the frontend can create a blob URL
    without storing audio data to R2.  Previews are cached in memory
    per voice+language+style combination for the lifetime of the server process.
    """
    style_params = get_style_params(narration_style)
    # Always derive the full BCP-47 code from the voice_id so Google TTS never
    # receives a mismatched pair (e.g. language_code='es' with voice 'es-US-Neural2-A').
    language_code = _derive_language_code(voice_id, language_code)
    cache_key    = _cache_key(voice_id, language_code, style_params)
    lang_short   = language_code[:2].lower()
    text         = _PREVIEW_TEXTS.get(lang_short, _DEFAULT_PREVIEW_TEXT)

    # Fast path — return cached bytes without hitting TTS API
    async with _cache_lock:
        if cache_key in _cache:
            _cache.move_to_end(cache_key)  # mark as recently used
            return Response(content=_cache[cache_key], media_type="audio/mpeg")

    # Slow path — synthesize and cache
    try:
        logger.info(
            "voice_preview_requested",
            user_id=str(current_user.id),
            voice_id=voice_id,
            language_code=language_code,
            narration_style=narration_style or "default",
            speaking_rate=style_params.speaking_rate,
            pitch=style_params.pitch,
        )
        provider    = GoogleTTSProvider()
        audio_bytes: bytes = await provider.synthesize(
            text,
            voice_id,
            language_code,
            speaking_rate=style_params.speaking_rate,
            pitch=style_params.pitch,
        )

        async with _cache_lock:
            _cache[cache_key] = audio_bytes
            _cache.move_to_end(cache_key)
            while len(_cache) > _CACHE_MAX_ENTRIES:
                _cache.popitem(last=False)  # evict least recently used

        logger.info(
            "voice_preview_style_applied",
            user_id=str(current_user.id),
            voice_id=voice_id,
            narration_style=narration_style or "default",
            speaking_rate=style_params.speaking_rate,
            pitch=style_params.pitch,
            bytes=len(audio_bytes),
        )
        return Response(content=audio_bytes, media_type="audio/mpeg")

    except TTSProviderError as exc:
        logger.warning(
            "voice_preview_failed",
            user_id=str(current_user.id),
            voice_id=voice_id,
            error=str(exc),
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Voice preview generation failed. Please try again.",
        ) from exc
    except Exception as exc:
        logger.error(
            "voice_preview_unexpected",
            user_id=str(current_user.id),
            voice_id=voice_id,
            error=str(exc),
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Voice preview unavailable.",
        ) from exc

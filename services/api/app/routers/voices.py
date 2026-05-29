"""
Voice Preview Router
====================
Lightweight endpoint for generating short TTS preview samples.

Each voice+language combination is synthesized once per server process
and the audio bytes are cached in memory. Subsequent calls skip TTS
entirely and serve the cached bytes directly.

Intentionally bypasses Celery, quota tracking, and cost events:
previews use a fixed ~90-char text that costs <$0.002 per voice,
are globally cached, and are not attributed to user quota.
"""

import asyncio
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import Response

from app.core.logging_config import get_logger
from app.core.auth_dependencies import get_current_active_user
from app.db.models.user import User
from app.services.tts.google_provider import GoogleTTSProvider
from app.services.tts.base import TTSProviderError

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

# Global cache: "voice_id:language_code" → MP3 bytes
_cache: dict[str, bytes] = {}
_cache_lock = asyncio.Lock()


@router.get("/preview")
async def preview_voice(
    voice_id:      str,
    language_code: str = "en-US",
    current_user:  User = Depends(get_current_active_user),
) -> Response:
    """
    Stream a short TTS audio sample for the given voice.

    Returns raw MP3 bytes so the frontend can create a blob URL
    without storing audio data to R2.  Previews are cached in memory
    for the lifetime of the server process.
    """
    cache_key  = f"{voice_id}:{language_code}"
    lang_short = language_code[:2].lower()
    text       = _PREVIEW_TEXTS.get(lang_short, _DEFAULT_PREVIEW_TEXT)

    # Fast path — return cached bytes without hitting TTS API
    async with _cache_lock:
        if cache_key in _cache:
            return Response(content=_cache[cache_key], media_type="audio/mpeg")

    # Slow path — synthesize and cache
    try:
        logger.info(
            "voice_preview_requested",
            user_id=str(current_user.id),
            voice_id=voice_id,
            language_code=language_code,
        )
        provider    = GoogleTTSProvider()
        audio_bytes: bytes = await provider.synthesize(text, voice_id, language_code)

        async with _cache_lock:
            _cache[cache_key] = audio_bytes

        logger.info(
            "voice_preview_generated",
            user_id=str(current_user.id),
            voice_id=voice_id,
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

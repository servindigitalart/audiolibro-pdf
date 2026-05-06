"""
Google Cloud TTS Provider
==========================
BLOCK 6A: Google Cloud Text-to-Speech integration.

This provider implements the TTSProvider interface using Google Cloud's
Text-to-Speech API with WaveNet and Neural2 voices.

Pricing (as of 2024):
- WaveNet voices: $16 per 1 million characters
- Neural2 voices: $16 per 1 million characters
- Standard voices: $4 per 1 million characters

We use Neural2 for best quality.
"""

import asyncio
import logging
from typing import Optional

from google.cloud import texttospeech_v1
from google.api_core import exceptions as google_exceptions
from google.oauth2 import service_account

from app.core.config import settings
from app.services.tts.base import (
    TTSProvider,
    TTSProviderError,
    TTSQuotaExceededError,
    TTSInvalidInputError,
    TTSNetworkError,
)

logger = logging.getLogger(__name__)


class GoogleTTSProvider(TTSProvider):
    """
    Google Cloud Text-to-Speech provider.
    
    Features:
    - High-quality Neural2 voices
    - Multi-language support
    - MP3 audio output
    - Async-safe execution
    - Detailed error handling
    """
    
    # Pricing in USD per character
    COST_PER_CHARACTER = 16.0 / 1_000_000  # $16 per 1M characters (Neural2)
    
    # API limits
    MAX_TEXT_LENGTH = 5000  # Google TTS limit per request
    
    def __init__(self):
        """Initialize Google Cloud TTS client."""
        self.client: Optional[texttospeech_v1.TextToSpeechClient] = None
        self._initialize_client()
    
    def _initialize_client(self):
        """Initialize the Google Cloud TTS client with credentials."""
        try:
            # Check if we have service account credentials
            if hasattr(settings, 'google_tts_credentials_json') and settings.google_tts_credentials_json:
                # Use service account JSON
                credentials = service_account.Credentials.from_service_account_file(
                    settings.google_tts_credentials_json
                )
                self.client = texttospeech_v1.TextToSpeechClient(credentials=credentials)
            elif hasattr(settings, 'google_tts_api_key') and settings.google_tts_api_key:
                # Use API key (simpler but less secure)
                self.client = texttospeech_v1.TextToSpeechClient()
            else:
                # Use application default credentials (for GCP environments)
                self.client = texttospeech_v1.TextToSpeechClient()
            
            logger.info("Google Cloud TTS client initialized successfully")
            
        except Exception as e:
            logger.error(f"Failed to initialize Google TTS client: {str(e)}")
            raise TTSProviderError(
                message="Failed to initialize Google TTS",
                provider="google",
                original_error=e
            )
    
    async def synthesize(
        self,
        text: str,
        voice_id: str,
        language_code: str,
    ) -> bytes:
        """
        Convert text to speech using Google Cloud TTS.
        
        Args:
            text: Text to synthesize (max 5000 characters per Google limit)
            voice_id: Google voice name (e.g., 'en-US-Neural2-A')
            language_code: Language code (e.g., 'en-US')
            
        Returns:
            MP3 audio data as bytes
            
        Raises:
            TTSInvalidInputError: If text is too long or invalid
            TTSQuotaExceededError: If quota is exceeded
            TTSNetworkError: If network request fails
            TTSProviderError: For other errors
        """
        # Validate input
        if not text or not text.strip():
            raise TTSInvalidInputError(
                message="Text cannot be empty",
                provider="google"
            )
        
        if len(text) > self.MAX_TEXT_LENGTH:
            raise TTSInvalidInputError(
                message=f"Text exceeds maximum length of {self.MAX_TEXT_LENGTH} characters",
                provider="google"
            )
        
        logger.info(
            f"Synthesizing {len(text)} characters with Google TTS",
            extra={
                "character_count": len(text),
                "voice_id": voice_id,
                "language_code": language_code
            }
        )
        
        try:
            # Prepare synthesis input
            synthesis_input = texttospeech_v1.SynthesisInput(text=text)
            
            # Configure voice parameters
            voice = texttospeech_v1.VoiceSelectionParams(
                language_code=language_code,
                name=voice_id,
            )
            
            # Configure audio output as MP3
            audio_config = texttospeech_v1.AudioConfig(
                audio_encoding=texttospeech_v1.AudioEncoding.MP3,
                speaking_rate=1.0,  # Normal speed
                pitch=0.0,  # Normal pitch
            )
            
            # Run synthesis in executor to avoid blocking
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None,
                self._synthesize_sync,
                synthesis_input,
                voice,
                audio_config
            )
            
            logger.info(
                f"Successfully synthesized {len(text)} characters",
                extra={
                    "character_count": len(text),
                    "audio_size_bytes": len(response.audio_content)
                }
            )
            
            return response.audio_content
            
        except google_exceptions.InvalidArgument as e:
            logger.error(f"Invalid input for Google TTS: {str(e)}")
            raise TTSInvalidInputError(
                message=f"Invalid input: {str(e)}",
                provider="google",
                original_error=e
            )
        
        except google_exceptions.ResourceExhausted as e:
            logger.error(f"Google TTS quota exceeded: {str(e)}")
            raise TTSQuotaExceededError(
                message="TTS quota exceeded",
                provider="google",
                original_error=e
            )
        
        except (google_exceptions.ServiceUnavailable, google_exceptions.DeadlineExceeded) as e:
            logger.error(f"Google TTS network error: {str(e)}")
            raise TTSNetworkError(
                message=f"Network error: {str(e)}",
                provider="google",
                original_error=e
            )
        
        except Exception as e:
            logger.error(f"Unexpected Google TTS error: {str(e)}", exc_info=True)
            raise TTSProviderError(
                message=f"Synthesis failed: {str(e)}",
                provider="google",
                original_error=e
            )
    
    def _synthesize_sync(
        self,
        synthesis_input: texttospeech_v1.SynthesisInput,
        voice: texttospeech_v1.VoiceSelectionParams,
        audio_config: texttospeech_v1.AudioConfig,
    ) -> texttospeech_v1.SynthesizeSpeechResponse:
        """
        Synchronous synthesis method for executor.
        
        This is called from run_in_executor to avoid blocking the event loop.
        """
        return self.client.synthesize_speech(
            input=synthesis_input,
            voice=voice,
            audio_config=audio_config
        )
    
    def estimate_cost(self, character_count: int) -> float:
        """
        Estimate cost for synthesizing text.
        
        Args:
            character_count: Number of characters to synthesize
            
        Returns:
            Estimated cost in USD
        """
        return character_count * self.COST_PER_CHARACTER
    
    def get_provider_name(self) -> str:
        """Get provider name."""
        return "google"

"""
TTS Provider Abstraction
========================
BLOCK 6A: Abstract base class for Text-to-Speech providers.

This abstraction allows Sonoro to support multiple TTS providers
(Google Cloud TTS, Amazon Polly, Azure TTS, etc.) with a unified interface.
"""

from abc import ABC, abstractmethod
from typing import Optional


class TTSProvider(ABC):
    """
    Abstract base class for TTS providers.
    
    All TTS providers must implement this interface to ensure
    consistent behavior across the application.
    
    Design principles:
    - Provider-agnostic: Can swap providers without changing business logic
    - Async-safe: All methods support async execution
    - Cost-aware: Built-in cost estimation
    - Simple: Minimal required interface
    """
    
    @abstractmethod
    async def synthesize(
        self,
        text: str,
        voice_id: str,
        language_code: str,
    ) -> bytes:
        """
        Convert text to speech audio.
        
        Args:
            text: Text to convert to speech
            voice_id: Provider-specific voice identifier
            language_code: Language code (e.g., 'en-US', 'es-ES')
            
        Returns:
            Audio data in MP3 format as bytes
            
        Raises:
            TTSProviderError: If synthesis fails
        """
        pass
    
    @abstractmethod
    def estimate_cost(self, character_count: int) -> float:
        """
        Estimate cost for synthesizing a given number of characters.
        
        Args:
            character_count: Number of characters to synthesize
            
        Returns:
            Estimated cost in USD
        """
        pass
    
    @abstractmethod
    def get_provider_name(self) -> str:
        """
        Get the name of this provider.
        
        Returns:
            Provider name (e.g., 'google', 'amazon', 'azure')
        """
        pass


class TTSProviderError(Exception):
    """Base exception for TTS provider errors."""
    
    def __init__(self, message: str, provider: str, original_error: Optional[Exception] = None):
        self.message = message
        self.provider = provider
        self.original_error = original_error
        super().__init__(f"[{provider}] {message}")


class TTSQuotaExceededError(TTSProviderError):
    """Raised when TTS provider quota is exceeded."""
    pass


class TTSInvalidInputError(TTSProviderError):
    """Raised when input text is invalid."""
    pass


class TTSNetworkError(TTSProviderError):
    """Raised when network communication fails."""
    pass

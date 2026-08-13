"""
Audio Processing Exceptions
============================
Raised by the ID3 tagging path (`metadata.py`).

The assembly and normalization exceptions that used to live here went with
their modules in Phase 0D.  AudioProcessingError stays as the shared base the
three below inherit from.
"""


class AudioProcessingError(Exception):
    """Base exception for audio processing errors."""
    pass


class AudioMetadataError(AudioProcessingError):
    """Exception raised during metadata tagging."""
    pass


class InvalidAudioFileError(AudioProcessingError):
    """Exception raised when audio file is invalid or corrupted."""
    pass


class AudioFileNotFoundError(AudioProcessingError):
    """Exception raised when audio file is not found."""
    pass

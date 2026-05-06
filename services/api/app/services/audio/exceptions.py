"""
Audio Processing Exceptions
============================
BLOCK 6C: Audio Assembly & Output Layer

Custom exceptions for audio processing operations.
"""


class AudioProcessingError(Exception):
    """Base exception for audio processing errors."""
    pass


class AudioAssemblyError(AudioProcessingError):
    """Exception raised during audio concatenation."""
    pass


class AudioNormalizationError(AudioProcessingError):
    """Exception raised during audio normalization."""
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


class BitrateInconsistencyError(AudioAssemblyError):
    """Exception raised when chapter bitrates don't match."""
    pass

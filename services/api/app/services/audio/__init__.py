"""
Audio Processing Module
=======================
BLOCK 6C: Audio Assembly & Output Layer

Provides audio concatenation, normalization, and metadata tagging
for final audiobook generation.

Components:
- AudioAssembler: Concatenate chapter MP3 files
- AudioNormalizer: Normalize loudness and trim silence
- AudioMetadataWriter: Add ID3 tags
"""

from app.services.audio.assembler import AudioAssembler
from app.services.audio.normalizer import AudioNormalizer
from app.services.audio.metadata import AudioMetadataWriter
from app.services.audio.exceptions import (
    AudioProcessingError,
    AudioAssemblyError,
    AudioNormalizationError,
    AudioMetadataError,
    InvalidAudioFileError,
)

__all__ = [
    "AudioAssembler",
    "AudioNormalizer",
    "AudioMetadataWriter",
    "AudioProcessingError",
    "AudioAssemblyError",
    "AudioNormalizationError",
    "AudioMetadataError",
    "InvalidAudioFileError",
]

"""
Audio Processing Module
=======================
ID3 tagging for the assembled audiobook.

Concatenation lives in the worker (`_ffmpeg_concat` — the ffmpeg concat demuxer,
which keeps no audio in RAM); the pydub-based AudioAssembler and AudioNormalizer
that used to live here were never called by it and were deleted in Phase 0D.
Loudness normalization is a Phase 2 item (audit 2.4, audio mastering) and will
be built as an ffmpeg filter, not resurrected from pydub.
"""

from app.services.audio.metadata import AudioMetadataWriter
from app.services.audio.exceptions import (
    AudioFileNotFoundError,
    AudioMetadataError,
    InvalidAudioFileError,
)

__all__ = [
    "AudioMetadataWriter",
    "AudioFileNotFoundError",
    "AudioMetadataError",
    "InvalidAudioFileError",
]

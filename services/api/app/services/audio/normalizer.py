"""
Audio Normalizer
================
BLOCK 6C: Audio Assembly & Output Layer

Normalizes audio loudness to consistent dBFS levels and optionally
trims silence from beginning and end.

Features:
- dBFS normalization
- Consistent loudness across audiobooks
- Optional silence trimming
- Async-safe operations
"""

import asyncio
import logging
import os
from typing import Optional, Tuple
from dataclasses import dataclass

from pydub import AudioSegment
from pydub.effects import normalize
from pydub.silence import detect_leading_silence

from app.services.audio.exceptions import (
    AudioNormalizationError,
    InvalidAudioFileError,
    AudioFileNotFoundError,
)

logger = logging.getLogger(__name__)


@dataclass
class NormalizationMetrics:
    """Metrics from normalization operation."""
    original_dbfs: float
    normalized_dbfs: float
    trim_start_ms: int
    trim_end_ms: int
    duration_before_seconds: float
    duration_after_seconds: float


class AudioNormalizer:
    """
    Normalizes audio loudness and trims silence.
    
    This class handles:
    - Normalizing audio to target dBFS level
    - Ensuring consistent loudness across audiobooks
    - Optionally trimming leading/trailing silence
    - Preserving audio quality
    
    Example:
        normalizer = AudioNormalizer(target_dbfs=-20.0)
        output_path, metrics = await normalizer.normalize(
            input_path="/tmp/audiobook.mp3",
            output_path="/tmp/audiobook_normalized.mp3",
            trim_silence=True
        )
    """
    
    def __init__(
        self,
        target_dbfs: float = -20.0,
        silence_threshold_db: int = -40,
        min_silence_len_ms: int = 1000,
    ):
        """
        Initialize audio normalizer.
        
        Args:
            target_dbfs: Target loudness in dBFS (default: -20.0)
            silence_threshold_db: Silence detection threshold (default: -40)
            min_silence_len_ms: Minimum silence length to trim (default: 1000ms)
        """
        self.target_dbfs = target_dbfs
        self.silence_threshold_db = silence_threshold_db
        self.min_silence_len_ms = min_silence_len_ms
        
    async def normalize(
        self,
        input_path: str,
        output_path: str,
        trim_silence: bool = True,
    ) -> Tuple[str, NormalizationMetrics]:
        """
        Normalize audio loudness and optionally trim silence.
        
        Args:
            input_path: Input audio file path
            output_path: Output audio file path
            trim_silence: Whether to trim leading/trailing silence
            
        Returns:
            Tuple of (output_path, metrics)
            
        Raises:
            AudioNormalizationError: If normalization fails
            AudioFileNotFoundError: If input file not found
            InvalidAudioFileError: If audio file is corrupted
        """
        if not os.path.exists(input_path):
            raise AudioFileNotFoundError(f"Input file not found: {input_path}")
            
        logger.info(
            f"Starting audio normalization",
            extra={
                "input_path": input_path,
                "target_dbfs": self.target_dbfs,
                "trim_silence": trim_silence,
            }
        )
        
        try:
            # Run blocking I/O in thread pool
            loop = asyncio.get_event_loop()
            output_path, metrics = await loop.run_in_executor(
                None,
                self._normalize_sync,
                input_path,
                output_path,
                trim_silence,
            )
            
            logger.info(
                f"Audio normalization complete",
                extra={
                    "original_dbfs": metrics.original_dbfs,
                    "normalized_dbfs": metrics.normalized_dbfs,
                    "trim_start_ms": metrics.trim_start_ms,
                    "trim_end_ms": metrics.trim_end_ms,
                    "duration_change_seconds": (
                        metrics.duration_after_seconds - metrics.duration_before_seconds
                    ),
                }
            )
            
            return output_path, metrics
            
        except Exception as e:
            logger.error(
                f"Audio normalization failed: {str(e)}",
                exc_info=True,
                extra={"input_path": input_path}
            )
            raise
            
    def _normalize_sync(
        self,
        input_path: str,
        output_path: str,
        trim_silence: bool,
    ) -> Tuple[str, NormalizationMetrics]:
        """
        Synchronous normalization implementation (runs in thread pool).
        
        Args:
            input_path: Input audio file path
            output_path: Output audio file path
            trim_silence: Whether to trim silence
            
        Returns:
            Tuple of (output_path, metrics)
        """
        try:
            # Load audio
            audio = AudioSegment.from_mp3(input_path)
            
            # Get original metrics
            original_dbfs = audio.dBFS
            duration_before_ms = len(audio)
            duration_before_seconds = duration_before_ms / 1000.0
            
            logger.debug(
                f"Loaded audio for normalization",
                extra={
                    "duration_seconds": duration_before_seconds,
                    "original_dbfs": original_dbfs,
                }
            )
            
            # Trim silence if requested
            trim_start_ms = 0
            trim_end_ms = 0
            
            if trim_silence:
                # Detect leading silence
                trim_start_ms = detect_leading_silence(
                    audio,
                    silence_threshold=self.silence_threshold_db,
                    chunk_size=10,
                )
                
                # Detect trailing silence (reverse audio)
                audio_reversed = audio.reverse()
                trim_end_ms = detect_leading_silence(
                    audio_reversed,
                    silence_threshold=self.silence_threshold_db,
                    chunk_size=10,
                )
                
                # Only trim if silence is longer than minimum threshold
                if trim_start_ms > self.min_silence_len_ms:
                    logger.debug(f"Trimming {trim_start_ms}ms leading silence")
                    audio = audio[trim_start_ms:]
                else:
                    trim_start_ms = 0
                    
                if trim_end_ms > self.min_silence_len_ms:
                    logger.debug(f"Trimming {trim_end_ms}ms trailing silence")
                    audio = audio[:-trim_end_ms]
                else:
                    trim_end_ms = 0
            
            # Normalize to target dBFS
            logger.debug(f"Normalizing to {self.target_dbfs} dBFS")
            
            # Apply normalization
            normalized_audio = normalize(audio, headroom=0.1)
            
            # Adjust to exact target dBFS
            change_in_dbfs = self.target_dbfs - normalized_audio.dBFS
            normalized_audio = normalized_audio + change_in_dbfs
            
            # Get final metrics
            normalized_dbfs = normalized_audio.dBFS
            duration_after_ms = len(normalized_audio)
            duration_after_seconds = duration_after_ms / 1000.0
            
            # Ensure output directory exists
            os.makedirs(os.path.dirname(output_path), exist_ok=True)
            
            # Export normalized audio
            logger.debug(f"Exporting normalized audio to {output_path}")
            normalized_audio.export(
                output_path,
                format="mp3",
                bitrate="128k",
                parameters=["-q:a", "2"],  # High quality VBR
            )
            
            # Create metrics
            metrics = NormalizationMetrics(
                original_dbfs=original_dbfs,
                normalized_dbfs=normalized_dbfs,
                trim_start_ms=trim_start_ms,
                trim_end_ms=trim_end_ms,
                duration_before_seconds=duration_before_seconds,
                duration_after_seconds=duration_after_seconds,
            )
            
            return output_path, metrics
            
        except Exception as e:
            raise AudioNormalizationError(f"Normalization failed: {str(e)}")
    
    async def analyze_loudness(self, audio_path: str) -> float:
        """
        Analyze audio loudness without modification.
        
        Args:
            audio_path: Path to audio file
            
        Returns:
            Current dBFS level
            
        Raises:
            AudioFileNotFoundError: If file not found
            InvalidAudioFileError: If audio is corrupted
        """
        if not os.path.exists(audio_path):
            raise AudioFileNotFoundError(f"Audio file not found: {audio_path}")
            
        try:
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(
                None,
                self._analyze_loudness_sync,
                audio_path,
            )
        except Exception as e:
            raise AudioNormalizationError(f"Loudness analysis failed: {str(e)}")
    
    def _analyze_loudness_sync(self, audio_path: str) -> float:
        """Synchronous loudness analysis."""
        audio = AudioSegment.from_mp3(audio_path)
        return audio.dBFS

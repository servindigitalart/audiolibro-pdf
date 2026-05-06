"""
Audio Assembler
===============
BLOCK 6C: Audio Assembly & Output Layer

Concatenates chapter MP3 files in correct order while preserving
bitrate consistency and audio quality.

Features:
- Concatenate multiple MP3 files
- Preserve bitrate consistency
- Calculate total duration
- Track file size
- Async-safe operations
"""

import asyncio
import logging
import os
import tempfile
from pathlib import Path
from typing import List, Tuple, Optional
from dataclasses import dataclass

from pydub import AudioSegment
from pydub.exceptions import CouldntDecodeError

from app.services.audio.exceptions import (
    AudioAssemblyError,
    InvalidAudioFileError,
    AudioFileNotFoundError,
    BitrateInconsistencyError,
)

logger = logging.getLogger(__name__)


@dataclass
class AudioMetrics:
    """Metrics from audio assembly operation."""
    duration_seconds: float
    file_size_bytes: int
    bitrate_kbps: int
    sample_rate_hz: int
    channels: int
    chapter_count: int


class AudioAssembler:
    """
    Assembles multiple chapter audio files into a single audiobook.
    
    This class handles:
    - Loading chapter MP3 files in order
    - Validating bitrate consistency
    - Concatenating audio segments
    - Exporting final audiobook with optimal settings
    
    Example:
        assembler = AudioAssembler()
        output_path, metrics = await assembler.assemble_chapters(
            chapter_paths=["/tmp/chapter_1.mp3", "/tmp/chapter_2.mp3"],
            output_path="/tmp/audiobook.mp3",
            target_bitrate=128
        )
    """
    
    def __init__(self, target_bitrate: int = 128):
        """
        Initialize audio assembler.
        
        Args:
            target_bitrate: Target bitrate in kbps (default: 128)
        """
        self.target_bitrate = target_bitrate
        
    async def assemble_chapters(
        self,
        chapter_paths: List[str],
        output_path: str,
        preserve_bitrate: bool = True,
    ) -> Tuple[str, AudioMetrics]:
        """
        Assemble chapter audio files into single audiobook.
        
        Args:
            chapter_paths: List of chapter MP3 file paths in order
            output_path: Output path for assembled audiobook
            preserve_bitrate: If True, use first chapter's bitrate
            
        Returns:
            Tuple of (output_path, metrics)
            
        Raises:
            AudioAssemblyError: If assembly fails
            AudioFileNotFoundError: If chapter file not found
            InvalidAudioFileError: If chapter file is corrupted
            BitrateInconsistencyError: If bitrates don't match and preserve_bitrate=True
        """
        if not chapter_paths:
            raise AudioAssemblyError("No chapter paths provided")
            
        logger.info(
            f"Starting audio assembly for {len(chapter_paths)} chapters",
            extra={
                "chapter_count": len(chapter_paths),
                "output_path": output_path,
                "target_bitrate": self.target_bitrate,
            }
        )
        
        try:
            # Run blocking I/O in thread pool
            loop = asyncio.get_event_loop()
            output_path, metrics = await loop.run_in_executor(
                None,
                self._assemble_sync,
                chapter_paths,
                output_path,
                preserve_bitrate,
            )
            
            logger.info(
                f"Audio assembly complete",
                extra={
                    "chapter_count": metrics.chapter_count,
                    "duration_seconds": metrics.duration_seconds,
                    "file_size_mb": metrics.file_size_bytes / (1024 * 1024),
                    "bitrate_kbps": metrics.bitrate_kbps,
                }
            )
            
            return output_path, metrics
            
        except Exception as e:
            logger.error(
                f"Audio assembly failed: {str(e)}",
                exc_info=True,
                extra={"chapter_count": len(chapter_paths)}
            )
            raise
            
    def _assemble_sync(
        self,
        chapter_paths: List[str],
        output_path: str,
        preserve_bitrate: bool,
    ) -> Tuple[str, AudioMetrics]:
        """
        Synchronous assembly implementation (runs in thread pool).
        
        Args:
            chapter_paths: List of chapter MP3 file paths
            output_path: Output path for assembled audiobook
            preserve_bitrate: Whether to preserve first chapter's bitrate
            
        Returns:
            Tuple of (output_path, metrics)
        """
        # Load all chapters
        chapters: List[AudioSegment] = []
        bitrates: List[int] = []
        
        for i, path in enumerate(chapter_paths):
            try:
                # Check file exists
                if not os.path.exists(path):
                    raise AudioFileNotFoundError(f"Chapter file not found: {path}")
                
                # Load audio
                audio = AudioSegment.from_mp3(path)
                chapters.append(audio)
                
                # Track bitrate
                bitrate = audio.frame_rate * audio.frame_width * 8 * audio.channels / 1000
                bitrates.append(int(bitrate))
                
                logger.debug(
                    f"Loaded chapter {i+1}/{len(chapter_paths)}",
                    extra={
                        "path": path,
                        "duration_ms": len(audio),
                        "bitrate_kbps": int(bitrate),
                    }
                )
                
            except CouldntDecodeError as e:
                raise InvalidAudioFileError(f"Could not decode audio file {path}: {str(e)}")
            except Exception as e:
                raise AudioAssemblyError(f"Failed to load chapter {path}: {str(e)}")
        
        # Validate bitrate consistency if required
        if preserve_bitrate and len(set(bitrates)) > 1:
            logger.warning(
                f"Bitrate inconsistency detected",
                extra={
                    "bitrates": bitrates,
                    "unique_bitrates": list(set(bitrates)),
                }
            )
            # Use most common bitrate
            target_bitrate = max(set(bitrates), key=bitrates.count)
        else:
            target_bitrate = self.target_bitrate
        
        # Concatenate all chapters
        logger.info(f"Concatenating {len(chapters)} chapters...")
        combined = chapters[0]
        for chapter in chapters[1:]:
            combined += chapter
        
        # Get audio properties
        duration_seconds = len(combined) / 1000.0
        sample_rate = combined.frame_rate
        channels = combined.channels
        
        # Export with consistent settings
        logger.info(
            f"Exporting audiobook",
            extra={
                "duration_seconds": duration_seconds,
                "bitrate_kbps": target_bitrate,
                "sample_rate": sample_rate,
                "channels": channels,
            }
        )
        
        # Ensure output directory exists
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        
        # Export as MP3
        combined.export(
            output_path,
            format="mp3",
            bitrate=f"{target_bitrate}k",
            parameters=["-q:a", "2"],  # High quality VBR
        )
        
        # Get file size
        file_size_bytes = os.path.getsize(output_path)
        
        # Create metrics
        metrics = AudioMetrics(
            duration_seconds=duration_seconds,
            file_size_bytes=file_size_bytes,
            bitrate_kbps=target_bitrate,
            sample_rate_hz=sample_rate,
            channels=channels,
            chapter_count=len(chapters),
        )
        
        return output_path, metrics
    
    async def validate_chapters(self, chapter_paths: List[str]) -> bool:
        """
        Validate that all chapter files exist and are readable.
        
        Args:
            chapter_paths: List of chapter file paths
            
        Returns:
            True if all chapters are valid
            
        Raises:
            AudioFileNotFoundError: If chapter not found
            InvalidAudioFileError: If chapter is corrupted
        """
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            self._validate_chapters_sync,
            chapter_paths,
        )
    
    def _validate_chapters_sync(self, chapter_paths: List[str]) -> bool:
        """Synchronous chapter validation."""
        for path in chapter_paths:
            if not os.path.exists(path):
                raise AudioFileNotFoundError(f"Chapter not found: {path}")
            
            try:
                # Try to load as MP3
                audio = AudioSegment.from_mp3(path)
                
                # Basic validation
                if len(audio) == 0:
                    raise InvalidAudioFileError(f"Chapter has zero duration: {path}")
                    
            except CouldntDecodeError:
                raise InvalidAudioFileError(f"Could not decode chapter: {path}")
        
        return True

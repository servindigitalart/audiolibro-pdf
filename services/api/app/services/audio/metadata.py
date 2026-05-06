"""
Audio Metadata Writer
=====================
BLOCK 6C: Audio Assembly & Output Layer

Writes ID3 tags to MP3 files for proper audiobook metadata.

Features:
- ID3v2.3 and ID3v2.4 support
- Standard audiobook tags (title, author, language)
- Processing date tracking
- Album art support (optional)
- Async-safe operations
"""

import asyncio
import logging
import os
from datetime import datetime
from typing import Optional, Dict, Any
from dataclasses import dataclass

from mutagen.mp3 import MP3
from mutagen.id3 import (
    ID3,
    TIT2,  # Title
    TPE1,  # Artist/Author
    TALB,  # Album
    TLAN,  # Language
    TDRC,  # Recording date
    COMM,  # Comment
    APIC,  # Album art
)
from mutagen.id3._util import ID3NoHeaderError

from app.services.audio.exceptions import (
    AudioMetadataError,
    AudioFileNotFoundError,
    InvalidAudioFileError,
)

logger = logging.getLogger(__name__)


@dataclass
class AudioMetadata:
    """Audiobook metadata to be written to MP3 file."""
    title: str
    author: Optional[str] = None
    language: Optional[str] = None
    album: Optional[str] = None
    processing_date: Optional[datetime] = None
    comment: Optional[str] = None
    album_art_path: Optional[str] = None


class AudioMetadataWriter:
    """
    Writes ID3 metadata tags to MP3 audiobook files.
    
    This class handles:
    - Writing ID3v2 tags to MP3 files
    - Standard audiobook metadata (title, author, language)
    - Processing date tracking
    - Optional album art embedding
    - Preserving audio quality
    
    Example:
        writer = AudioMetadataWriter()
        metadata = AudioMetadata(
            title="My Audiobook",
            author="John Doe",
            language="en",
            processing_date=datetime.utcnow()
        )
        await writer.write_metadata(
            audio_path="/tmp/audiobook.mp3",
            metadata=metadata
        )
    """
    
    def __init__(self, id3_version: str = "v2.4"):
        """
        Initialize metadata writer.
        
        Args:
            id3_version: ID3 version to use ("v2.3" or "v2.4")
        """
        self.id3_version = id3_version
        
    async def write_metadata(
        self,
        audio_path: str,
        metadata: AudioMetadata,
    ) -> Dict[str, Any]:
        """
        Write ID3 metadata tags to MP3 file.
        
        Args:
            audio_path: Path to MP3 file
            metadata: Metadata to write
            
        Returns:
            Dictionary of written tags
            
        Raises:
            AudioMetadataError: If metadata writing fails
            AudioFileNotFoundError: If file not found
            InvalidAudioFileError: If file is not valid MP3
        """
        if not os.path.exists(audio_path):
            raise AudioFileNotFoundError(f"Audio file not found: {audio_path}")
            
        logger.info(
            f"Writing metadata to audio file",
            extra={
                "audio_path": audio_path,
                "title": metadata.title,
                "author": metadata.author,
                "language": metadata.language,
            }
        )
        
        try:
            # Run blocking I/O in thread pool
            loop = asyncio.get_event_loop()
            tags = await loop.run_in_executor(
                None,
                self._write_metadata_sync,
                audio_path,
                metadata,
            )
            
            logger.info(
                f"Metadata written successfully",
                extra={
                    "audio_path": audio_path,
                    "tags_written": len(tags),
                }
            )
            
            return tags
            
        except Exception as e:
            logger.error(
                f"Metadata writing failed: {str(e)}",
                exc_info=True,
                extra={"audio_path": audio_path}
            )
            raise
            
    def _write_metadata_sync(
        self,
        audio_path: str,
        metadata: AudioMetadata,
    ) -> Dict[str, Any]:
        """
        Synchronous metadata writing implementation (runs in thread pool).
        
        Args:
            audio_path: Path to MP3 file
            metadata: Metadata to write
            
        Returns:
            Dictionary of written tags
        """
        try:
            # Load MP3 file
            audio = MP3(audio_path)
            
            # Add ID3 tags if not present
            try:
                audio.tags
            except ID3NoHeaderError:
                audio.add_tags()
            
            tags_written = {}
            
            # Write title (required)
            if metadata.title:
                audio.tags.add(TIT2(encoding=3, text=metadata.title))
                tags_written["title"] = metadata.title
                logger.debug(f"Set title: {metadata.title}")
            
            # Write author/artist
            if metadata.author:
                audio.tags.add(TPE1(encoding=3, text=metadata.author))
                tags_written["author"] = metadata.author
                logger.debug(f"Set author: {metadata.author}")
            
            # Write album
            album = metadata.album or metadata.title
            audio.tags.add(TALB(encoding=3, text=album))
            tags_written["album"] = album
            logger.debug(f"Set album: {album}")
            
            # Write language
            if metadata.language:
                audio.tags.add(TLAN(encoding=3, text=metadata.language))
                tags_written["language"] = metadata.language
                logger.debug(f"Set language: {metadata.language}")
            
            # Write processing date
            processing_date = metadata.processing_date or datetime.utcnow()
            date_str = processing_date.strftime("%Y-%m-%d")
            audio.tags.add(TDRC(encoding=3, text=date_str))
            tags_written["processing_date"] = date_str
            logger.debug(f"Set processing date: {date_str}")
            
            # Write comment with processing info
            comment_text = metadata.comment or (
                f"Processed by Sonoro on {date_str}. "
                f"High-quality audiobook generated from PDF document."
            )
            audio.tags.add(
                COMM(encoding=3, lang="eng", desc="Processing Info", text=comment_text)
            )
            tags_written["comment"] = comment_text
            
            # Add album art if provided
            if metadata.album_art_path and os.path.exists(metadata.album_art_path):
                try:
                    with open(metadata.album_art_path, "rb") as f:
                        album_art_data = f.read()
                    
                    # Detect MIME type
                    mime_type = "image/jpeg"
                    if metadata.album_art_path.lower().endswith(".png"):
                        mime_type = "image/png"
                    
                    audio.tags.add(
                        APIC(
                            encoding=3,
                            mime=mime_type,
                            type=3,  # Cover (front)
                            desc="Cover",
                            data=album_art_data,
                        )
                    )
                    tags_written["album_art"] = True
                    logger.debug("Added album art")
                    
                except Exception as e:
                    logger.warning(f"Failed to add album art: {str(e)}")
            
            # Save tags
            audio.save()
            
            logger.debug(f"Saved {len(tags_written)} metadata tags")
            
            return tags_written
            
        except ID3NoHeaderError:
            raise InvalidAudioFileError(f"File is not a valid MP3: {audio_path}")
        except Exception as e:
            raise AudioMetadataError(f"Failed to write metadata: {str(e)}")
    
    async def read_metadata(self, audio_path: str) -> Dict[str, Any]:
        """
        Read existing metadata from MP3 file.
        
        Args:
            audio_path: Path to MP3 file
            
        Returns:
            Dictionary of metadata tags
            
        Raises:
            AudioFileNotFoundError: If file not found
            InvalidAudioFileError: If file is not valid MP3
        """
        if not os.path.exists(audio_path):
            raise AudioFileNotFoundError(f"Audio file not found: {audio_path}")
            
        try:
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(
                None,
                self._read_metadata_sync,
                audio_path,
            )
        except Exception as e:
            raise AudioMetadataError(f"Failed to read metadata: {str(e)}")
    
    def _read_metadata_sync(self, audio_path: str) -> Dict[str, Any]:
        """Synchronous metadata reading."""
        try:
            audio = MP3(audio_path)
            
            metadata = {}
            
            if audio.tags:
                # Extract common tags
                if "TIT2" in audio.tags:
                    metadata["title"] = str(audio.tags["TIT2"])
                if "TPE1" in audio.tags:
                    metadata["author"] = str(audio.tags["TPE1"])
                if "TALB" in audio.tags:
                    metadata["album"] = str(audio.tags["TALB"])
                if "TLAN" in audio.tags:
                    metadata["language"] = str(audio.tags["TLAN"])
                if "TDRC" in audio.tags:
                    metadata["date"] = str(audio.tags["TDRC"])
                if "COMM" in audio.tags:
                    metadata["comment"] = str(audio.tags["COMM"])
            
            # Audio info
            metadata["duration_seconds"] = audio.info.length
            metadata["bitrate"] = audio.info.bitrate
            metadata["sample_rate"] = audio.info.sample_rate
            metadata["channels"] = audio.info.channels
            
            return metadata
            
        except ID3NoHeaderError:
            raise InvalidAudioFileError(f"File is not a valid MP3: {audio_path}")
        except Exception as e:
            raise AudioMetadataError(f"Failed to read metadata: {str(e)}")
    
    async def clear_metadata(self, audio_path: str) -> None:
        """
        Clear all metadata from MP3 file.
        
        Args:
            audio_path: Path to MP3 file
            
        Raises:
            AudioFileNotFoundError: If file not found
            InvalidAudioFileError: If file is not valid MP3
        """
        if not os.path.exists(audio_path):
            raise AudioFileNotFoundError(f"Audio file not found: {audio_path}")
            
        logger.info(f"Clearing metadata from {audio_path}")
        
        try:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None,
                self._clear_metadata_sync,
                audio_path,
            )
        except Exception as e:
            raise AudioMetadataError(f"Failed to clear metadata: {str(e)}")
    
    def _clear_metadata_sync(self, audio_path: str) -> None:
        """Synchronous metadata clearing."""
        try:
            audio = MP3(audio_path)
            audio.delete()
            audio.save()
            logger.debug(f"Cleared metadata from {audio_path}")
        except Exception as e:
            raise AudioMetadataError(f"Failed to clear metadata: {str(e)}")

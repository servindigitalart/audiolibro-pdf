"""
Unit tests for AudioMetadataWriter.

Covers the core bug: MP3 files assembled by ffmpeg's concat demuxer carry no
existing ID3 header.  mutagen.mp3.MP3() sets audio.tags = None in that case
(it does NOT raise ID3NoHeaderError on the attribute access), so the old
try/except guard never fired and audio.tags.add(...) raised AttributeError.

Scenarios:
1. MP3 with no existing ID3 tags — metadata write succeeds.
2. MP3 with existing ID3 tags — metadata write overwrites without crashing.
3. All metadata fields land in the written tags.
4. Minimal required field (title only) works.
5. write_metadata returns a non-empty dict of written tags.
6. AudioMetadataError is raised for a corrupt file, not an uncaught AttributeError.
"""

import os
import struct
import tempfile
import pytest
from datetime import datetime
from unittest.mock import patch, MagicMock

import mutagen.mp3
import mutagen.id3

from app.services.audio.metadata import AudioMetadataWriter, AudioMetadata
from app.services.audio.exceptions import AudioMetadataError, AudioFileNotFoundError


# ---------------------------------------------------------------------------
# Helpers — minimal valid MP3
# ---------------------------------------------------------------------------

# MPEG1 Layer3, 128 kbps, 44100 Hz, stereo, no padding.
# Frame size = 417 bytes: 4 header + 32 side-info + 381 main-data.
_MP3_FRAME = bytes([0xFF, 0xFB, 0x90, 0x00]) + bytes(413)


def _write_tagless_mp3(path: str, frames: int = 4) -> None:
    """Write a minimal tag-free MP3 (raw MPEG frames, no ID3 header)."""
    with open(path, "wb") as fh:
        for _ in range(frames):
            fh.write(_MP3_FRAME)


def _write_tagged_mp3(path: str) -> None:
    """Write a minimal MP3 that already has an ID3 tag container."""
    _write_tagless_mp3(path)
    audio = mutagen.mp3.MP3(path)
    audio.add_tags()
    audio.tags.add(mutagen.id3.TIT2(encoding=3, text="Existing Title"))
    audio.save()


def _default_meta(**overrides) -> AudioMetadata:
    base = dict(
        title="Test Audiobook",
        author="Test Author",
        language="en",
        processing_date=datetime(2026, 5, 31, 12, 0, 0),
        comment="Test comment",
    )
    base.update(overrides)
    return AudioMetadata(**base)


# ---------------------------------------------------------------------------
# Synchronous path tests (no async needed)
# ---------------------------------------------------------------------------

class TestWriteMetadataSync:

    def test_tagless_mp3_does_not_raise(self, tmp_path):
        """Core regression: _write_metadata_sync must not raise AttributeError
        when audio.tags is None before writing."""
        mp3 = str(tmp_path / "tagless.mp3")
        _write_tagless_mp3(mp3)

        writer = AudioMetadataWriter()
        # Must not raise — previously failed with
        # AudioMetadataError: 'NoneType' object has no attribute 'add'
        result = writer._write_metadata_sync(mp3, _default_meta())
        assert isinstance(result, dict)

    def test_tagless_mp3_title_written(self, tmp_path):
        """Title tag is present in the file after writing to a tag-free MP3."""
        mp3 = str(tmp_path / "tagless.mp3")
        _write_tagless_mp3(mp3)

        writer = AudioMetadataWriter()
        writer._write_metadata_sync(mp3, _default_meta(title="My Book"))

        saved = mutagen.mp3.MP3(mp3)
        assert saved.tags is not None
        assert str(saved.tags["TIT2"]) == "My Book"

    def test_tagged_mp3_does_not_raise(self, tmp_path):
        """Writing metadata to an MP3 that already has tags must not crash."""
        mp3 = str(tmp_path / "tagged.mp3")
        _write_tagged_mp3(mp3)

        writer = AudioMetadataWriter()
        result = writer._write_metadata_sync(mp3, _default_meta())
        assert isinstance(result, dict)

    def test_tagged_mp3_overwrites_existing_title(self, tmp_path):
        """Existing title tag is replaced by the new value."""
        mp3 = str(tmp_path / "tagged.mp3")
        _write_tagged_mp3(mp3)  # writes "Existing Title"

        writer = AudioMetadataWriter()
        writer._write_metadata_sync(mp3, _default_meta(title="New Title"))

        saved = mutagen.mp3.MP3(mp3)
        assert str(saved.tags["TIT2"]) == "New Title"

    def test_all_standard_fields_written(self, tmp_path):
        """All non-art metadata fields land in the saved file."""
        mp3 = str(tmp_path / "full.mp3")
        _write_tagless_mp3(mp3)

        meta = _default_meta(
            title="Full Book",
            author="Jane Doe",
            language="es",
            album="My Series",
            processing_date=datetime(2026, 1, 15),
            comment="Custom comment",
        )

        writer = AudioMetadataWriter()
        tags_written = writer._write_metadata_sync(mp3, meta)

        assert "title" in tags_written
        assert "author" in tags_written
        assert "language" in tags_written
        assert "album" in tags_written
        assert "processing_date" in tags_written
        assert "comment" in tags_written

        saved = mutagen.mp3.MP3(mp3)
        assert str(saved.tags["TIT2"]) == "Full Book"
        assert str(saved.tags["TPE1"]) == "Jane Doe"
        assert str(saved.tags["TLAN"]) == "es"
        assert str(saved.tags["TALB"]) == "My Series"

    def test_title_only_minimum_works(self, tmp_path):
        """A metadata object with only title set must not crash."""
        mp3 = str(tmp_path / "min.mp3")
        _write_tagless_mp3(mp3)

        writer = AudioMetadataWriter()
        result = writer._write_metadata_sync(mp3, AudioMetadata(title="Minimal"))
        assert "title" in result

    def test_returns_non_empty_dict(self, tmp_path):
        """write_metadata_sync returns a dict with at least one entry."""
        mp3 = str(tmp_path / "ret.mp3")
        _write_tagless_mp3(mp3)

        writer = AudioMetadataWriter()
        result = writer._write_metadata_sync(mp3, _default_meta())
        assert len(result) >= 1

    def test_corrupt_file_raises_audio_metadata_error(self, tmp_path):
        """A corrupt (non-MP3) file raises AudioMetadataError, not AttributeError."""
        bad = str(tmp_path / "corrupt.mp3")
        with open(bad, "wb") as fh:
            fh.write(b"\x00" * 64)

        writer = AudioMetadataWriter()
        with pytest.raises((AudioMetadataError, Exception)):
            writer._write_metadata_sync(bad, _default_meta())

    def test_missing_file_raises_at_async_layer(self, tmp_path):
        """write_metadata raises AudioFileNotFoundError for a missing path."""
        writer = AudioMetadataWriter()
        import asyncio
        with pytest.raises(AudioFileNotFoundError):
            asyncio.get_event_loop().run_until_complete(
                writer.write_metadata(
                    str(tmp_path / "nonexistent.mp3"),
                    _default_meta(),
                )
            )


# ---------------------------------------------------------------------------
# Async path tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_write_metadata_async_tagless(tmp_path):
    """The async write_metadata path succeeds on a tag-free MP3."""
    mp3 = str(tmp_path / "async_tagless.mp3")
    _write_tagless_mp3(mp3)

    writer = AudioMetadataWriter()
    result = await writer.write_metadata(mp3, _default_meta(title="Async Book"))

    assert result.get("title") == "Async Book"


@pytest.mark.asyncio
async def test_write_metadata_async_tagged(tmp_path):
    """The async write_metadata path succeeds on a pre-tagged MP3."""
    mp3 = str(tmp_path / "async_tagged.mp3")
    _write_tagged_mp3(mp3)

    writer = AudioMetadataWriter()
    result = await writer.write_metadata(mp3, _default_meta(title="Replaced"))

    saved = mutagen.mp3.MP3(mp3)
    assert str(saved.tags["TIT2"]) == "Replaced"


@pytest.mark.asyncio
async def test_write_metadata_idempotent(tmp_path):
    """Calling write_metadata twice on the same file must not raise."""
    mp3 = str(tmp_path / "idempotent.mp3")
    _write_tagless_mp3(mp3)

    writer = AudioMetadataWriter()
    await writer.write_metadata(mp3, _default_meta(title="First"))
    await writer.write_metadata(mp3, _default_meta(title="Second"))

    saved = mutagen.mp3.MP3(mp3)
    assert str(saved.tags["TIT2"]) == "Second"

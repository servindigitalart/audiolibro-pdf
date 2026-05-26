"""
Unit tests for real-time processing progress tracking.

Covers:
- _chunk_text: correct chunk counts for short, exact, and oversized texts
- _tts_progress: 25-90% mapping formula
- _derive_stage: current_stage mapping and progress-based fallback
- Estimated time computation logic
- Progress never exceeds 100% or goes below 25% in tts_generation
- Zero-chunk edge case (empty document)
"""

import math
from datetime import datetime, timedelta
from unittest.mock import MagicMock

import pytest

from app.tasks.processing import _chunk_text
from app.routers.documents import _derive_stage, _STAGE_MAP


# ---------------------------------------------------------------------------
# _chunk_text
# ---------------------------------------------------------------------------

class TestChunkText:
    def test_short_text_is_single_chunk(self):
        assert _chunk_text("Hello world") == ["Hello world"]

    def test_exact_size_is_single_chunk(self):
        text = "x" * 4500
        chunks = _chunk_text(text)
        assert len(chunks) == 1

    def test_one_over_splits_into_two(self):
        text = "x" * 4501
        chunks = _chunk_text(text)
        assert len(chunks) == 2

    def test_double_size_makes_two_chunks(self):
        text = "x" * 9000
        chunks = _chunk_text(text)
        assert len(chunks) == 2

    def test_large_text_chunk_count(self):
        text = "x" * 45_000
        chunks = _chunk_text(text)
        assert len(chunks) == 10

    def test_prefers_paragraph_boundary(self):
        # Build a text with a paragraph break near the middle of the window
        part_a = "a" * 2500
        part_b = "b" * 2500
        text = part_a + "\n\n" + part_b  # total > 4500
        chunks = _chunk_text(text)
        # Split should happen at the blank line, not mid-word
        assert all(c.strip() for c in chunks)
        assert len(chunks) >= 2

    def test_prefers_sentence_boundary(self):
        # No paragraph break; has a sentence boundary in the window
        part_a = "Hello world. " * 200   # ~2600 chars, ends with ". "
        part_b = "More text. " * 200
        text = part_a + part_b
        chunks = _chunk_text(text)
        assert len(chunks) >= 2
        for c in chunks:
            assert len(c) <= 4500

    def test_empty_string_returns_single_empty_chunk(self):
        # Short-circuit path returns [text] for any text <= max_chars, including "".
        assert _chunk_text("") == [""]

    def test_all_chunks_within_limit(self):
        text = "word " * 10_000  # ~50 000 chars
        chunks = _chunk_text(text)
        assert all(len(c) <= 4500 for c in chunks)

    def test_custom_max_chars(self):
        text = "x" * 100
        chunks = _chunk_text(text, max_chars=30)
        assert len(chunks) == math.ceil(100 / 30)


# ---------------------------------------------------------------------------
# TTS progress formula: 25 + floor(completed/total * 65)
# ---------------------------------------------------------------------------

def _tts_progress(completed: int, total: int) -> int:
    if total <= 0:
        return 25
    return 25 + int(completed / total * 65)


class TestTtsProgressFormula:
    def test_zero_chunks_done_is_25(self):
        assert _tts_progress(0, 100) == 25

    def test_all_chunks_done_is_90(self):
        assert _tts_progress(100, 100) == 90

    def test_half_chunks_done_is_57_or_58(self):
        result = _tts_progress(50, 100)
        assert 57 <= result <= 58  # 25 + 32.5 floors to 57

    def test_single_chunk_total(self):
        assert _tts_progress(1, 1) == 90

    def test_zero_total_returns_25(self):
        assert _tts_progress(0, 0) == 25

    def test_progress_never_exceeds_90(self):
        for done in range(0, 201):
            assert _tts_progress(done, 200) <= 90

    def test_progress_never_below_25(self):
        for done in range(0, 201):
            assert _tts_progress(done, 200) >= 25

    def test_monotonically_increasing(self):
        total = 107
        pcts = [_tts_progress(done, total) for done in range(total + 1)]
        assert pcts == sorted(pcts)


# ---------------------------------------------------------------------------
# _derive_stage: current_stage (DB) overrides progress heuristic
# ---------------------------------------------------------------------------

class TestDeriveStage:
    def test_analyzing_stage(self):
        assert _derive_stage(5, "analyzing") == "analyzing"

    def test_chapter_detection_stage(self):
        assert _derive_stage(20, "chapter_detection") == "detecting_chapters"

    def test_tts_generation_stage(self):
        assert _derive_stage(60, "tts_generation") == "generating_audio"

    def test_final_assembly_stage(self):
        assert _derive_stage(92, "final_assembly") == "finalizing"

    def test_upload_finalize_stage(self):
        assert _derive_stage(97, "upload_finalize") == "finalizing"

    def test_unknown_stage_falls_back_to_analyzing(self):
        assert _derive_stage(5, "unknown_stage") == "analyzing"

    def test_no_stage_uses_progress_low(self):
        assert _derive_stage(10, None) == "analyzing"

    def test_no_stage_uses_progress_mid(self):
        assert _derive_stage(40, None) == "detecting_chapters"

    def test_no_stage_uses_progress_high(self):
        assert _derive_stage(75, None) == "generating_audio"

    def test_no_stage_uses_progress_final(self):
        assert _derive_stage(95, None) == "finalizing"

    def test_stage_map_covers_all_worker_stages(self):
        expected = {
            "analyzing", "chapter_detection",
            "tts_generation", "final_assembly", "upload_finalize",
        }
        assert set(_STAGE_MAP.keys()) == expected

    def test_current_stage_overrides_progress(self):
        # Even if progress is high, the explicit stage wins
        assert _derive_stage(95, "analyzing") == "analyzing"


# ---------------------------------------------------------------------------
# Estimated time remaining logic (mirrors documents.py computation)
# ---------------------------------------------------------------------------

def _estimate_remaining(completed: int, total: int, started_at: datetime) -> int | None:
    """Mirrors the estimation logic in the polling endpoint."""
    if completed <= 0 or total <= completed:
        return None
    elapsed = (datetime.utcnow() - started_at).total_seconds()
    rate = completed / max(elapsed, 1)
    if rate <= 0:
        return None
    return max(0, int((total - completed) / rate))


class TestEstimatedTimeRemaining:
    def test_returns_none_when_no_chunks_done(self):
        started = datetime.utcnow() - timedelta(seconds=60)
        assert _estimate_remaining(0, 100, started) is None

    def test_returns_none_when_all_chunks_done(self):
        started = datetime.utcnow() - timedelta(seconds=60)
        assert _estimate_remaining(100, 100, started) is None

    def test_roughly_correct_halfway(self):
        started = datetime.utcnow() - timedelta(seconds=50)
        result = _estimate_remaining(50, 100, started)
        # At 50% in 50s → 50 more seconds expected; allow ±5s tolerance
        assert result is not None
        assert 45 <= result <= 55

    def test_result_is_non_negative(self):
        started = datetime.utcnow() - timedelta(seconds=1)
        result = _estimate_remaining(99, 100, started)
        assert result is not None
        assert result >= 0

    def test_returns_none_when_completed_equals_total(self):
        started = datetime.utcnow() - timedelta(seconds=30)
        assert _estimate_remaining(100, 100, started) is None

    def test_large_job_estimate(self):
        # 107 chunks, 10 done in 20 seconds → rate=0.5/s, 97 remaining → ~194s
        started = datetime.utcnow() - timedelta(seconds=20)
        result = _estimate_remaining(10, 107, started)
        assert result is not None
        assert 180 <= result <= 210

"""
Unit tests for PreflightService.

Covers:
- Duration estimation from character count
- Processing time estimation
- Chapter count heuristic across page ranges
- Quota fit calculation (fits / exceeded)
- Language + voice resolution
- Oversized document quota detection
- Zero / edge-case inputs
"""

from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.services.preflight_service import (
    PreflightService,
    _TTS_CHARS_PER_SECOND,
    _TTS_CHUNK_SIZE,
    _PIPELINE_OVERHEAD_SECONDS,
    LANGUAGE_DISPLAY_MAP,
    VOICE_DISPLAY_MAP,
)


# ---------------------------------------------------------------------------
# Duration estimation
# ---------------------------------------------------------------------------

class TestEstimateDurationSeconds:
    def test_zero_chars_returns_zero(self):
        assert PreflightService._estimate_duration_seconds(0) == 0

    def test_negative_chars_returns_zero(self):
        assert PreflightService._estimate_duration_seconds(-100) == 0

    def test_small_text(self):
        # 140 chars ÷ 14 chars/sec = 10 seconds
        assert PreflightService._estimate_duration_seconds(140) == 10

    def test_book_length(self):
        # 62_722 chars ÷ 14 = 4480 seconds ≈ 74 minutes
        result = PreflightService._estimate_duration_seconds(62_722)
        assert 4450 <= result <= 4510

    def test_large_document(self):
        # 500_000 chars ÷ 14 = 35_714 seconds ≈ 9.9 hours
        result = PreflightService._estimate_duration_seconds(500_000)
        assert 35_500 <= result <= 36_000

    def test_result_uses_tts_chars_per_second_constant(self):
        chars = 1_400
        expected = chars // _TTS_CHARS_PER_SECOND
        assert PreflightService._estimate_duration_seconds(chars) == expected

    def test_minimum_one_second_for_small_text(self):
        assert PreflightService._estimate_duration_seconds(1) >= 1


# ---------------------------------------------------------------------------
# Processing time estimation
# ---------------------------------------------------------------------------

class TestEstimateProcessingMinutes:
    def test_zero_chars_returns_overhead_only(self):
        result = PreflightService._estimate_processing_minutes(0)
        expected = round(_PIPELINE_OVERHEAD_SECONDS / 60, 1)
        assert result == expected

    def test_single_chunk(self):
        # 4_500 chars → 1 chunk → 2s TTS + 120s overhead = 122s ≈ 2.0 min
        result = PreflightService._estimate_processing_minutes(4_500)
        assert 1.5 <= result <= 3.0

    def test_many_chunks(self):
        # 107 chunks × 2s + 120s = 334s ≈ 5.6 min
        chars = 107 * _TTS_CHUNK_SIZE
        result = PreflightService._estimate_processing_minutes(chars)
        assert 5.0 <= result <= 7.0

    def test_large_document_stays_reasonable(self):
        # 500_000 chars → ~111 chunks → ~4 min TTS + 2 min overhead
        result = PreflightService._estimate_processing_minutes(500_000)
        assert 4.0 <= result <= 10.0

    def test_returns_float_rounded_to_one_decimal(self):
        result = PreflightService._estimate_processing_minutes(10_000)
        assert isinstance(result, float)
        assert round(result, 1) == result


# ---------------------------------------------------------------------------
# Chapter count heuristic
# ---------------------------------------------------------------------------

class TestEstimateChapters:
    def test_none_returns_one(self):
        assert PreflightService._estimate_chapters(None) == 1

    def test_zero_returns_one(self):
        assert PreflightService._estimate_chapters(0) == 1

    def test_one_page_returns_one(self):
        assert PreflightService._estimate_chapters(1) == 1

    def test_ten_pages_returns_one(self):
        assert PreflightService._estimate_chapters(10) == 1

    def test_small_book(self):
        # 30 pages → 30 // 15 = 2
        assert PreflightService._estimate_chapters(30) == 2

    def test_medium_book(self):
        # 100 pages → 100 // 25 = 4
        assert PreflightService._estimate_chapters(100) == 4

    def test_large_book(self):
        # 350 pages → 350 // 35 = 10
        assert PreflightService._estimate_chapters(350) == 10

    def test_always_at_least_one(self):
        for pages in [0, 1, 5, 10, 11, 50, 100, 500]:
            assert PreflightService._estimate_chapters(pages) >= 1

    def test_monotonically_non_decreasing(self):
        prev = 0
        for pages in [0, 10, 20, 50, 100, 200, 500]:
            result = PreflightService._estimate_chapters(pages)
            assert result >= prev
            prev = result


# ---------------------------------------------------------------------------
# Quota fit calculation (async, uses mock DB)
# ---------------------------------------------------------------------------

def _make_user(plan_tier: str = "FREE"):
    user = MagicMock()
    user.id = uuid4()
    user.plan_tier = plan_tier
    return user


def _make_document(chars: int = 5_000, pages: int = 50, language: str = "en"):
    doc = MagicMock()
    doc.id = uuid4()
    doc.character_estimate = chars
    doc.page_count = pages
    doc.language_detected = language
    return doc


def _make_quota(chars_used: int = 0, plan_tier: str = "FREE"):
    from app.financial.cost.cost_models import UsageQuota
    quota = MagicMock(spec=UsageQuota)
    quota.characters_used = chars_used
    quota.jobs_created = 0
    now = datetime.utcnow()
    quota.period_start = now - timedelta(days=10)
    quota.period_end = now + timedelta(days=20)
    return quota


def _mock_db(quota):
    db = AsyncMock()
    exec_result = MagicMock()
    exec_result.scalar_one_or_none.return_value = quota
    db.execute = AsyncMock(return_value=exec_result)
    db.add = MagicMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    return db


class TestPreflightAnalyzeQuota:
    @pytest.mark.asyncio
    async def test_fits_current_plan_when_under_quota(self):
        user = _make_user("FREE")
        doc = _make_document(chars=5_000)
        quota = _make_quota(chars_used=0)
        db = _mock_db(quota)

        result = await PreflightService.analyze(doc, user, db)

        assert result.fits_current_plan is True
        assert result.quota_exceeded is False
        assert result.chars_remaining_after >= 0

    @pytest.mark.asyncio
    async def test_quota_exceeded_when_over_limit(self):
        user = _make_user("FREE")
        doc = _make_document(chars=8_000)      # 8k chars
        quota = _make_quota(chars_used=5_000)  # 5k already used → 10k limit exceeded
        db = _mock_db(quota)

        result = await PreflightService.analyze(doc, user, db)

        assert result.quota_exceeded is True
        assert result.fits_current_plan is False
        assert result.chars_remaining_after < 0

    @pytest.mark.asyncio
    async def test_pro_plan_has_higher_limit(self):
        user = _make_user("PRO")
        doc = _make_document(chars=50_000)
        quota = _make_quota(chars_used=0, plan_tier="PRO")
        db = _mock_db(quota)

        result = await PreflightService.analyze(doc, user, db)

        assert result.fits_current_plan is True
        assert result.chars_limit == 500_000

    @pytest.mark.asyncio
    async def test_remaining_after_equals_remaining_before_minus_chars(self):
        user = _make_user("FREE")
        doc = _make_document(chars=3_000)
        quota = _make_quota(chars_used=2_000)
        db = _mock_db(quota)

        result = await PreflightService.analyze(doc, user, db)

        assert result.chars_remaining_after == result.chars_remaining_before - doc.character_estimate

    @pytest.mark.asyncio
    async def test_language_and_voice_resolved(self):
        user = _make_user("FREE")
        doc = _make_document(chars=1_000, language="es")
        quota = _make_quota()
        db = _mock_db(quota)

        result = await PreflightService.analyze(doc, user, db)

        assert result.language == "es"
        assert result.language_name == "Spanish"
        assert "es" in result.voice_id.lower()
        assert len(result.available_voices) >= 1

    @pytest.mark.asyncio
    async def test_unknown_language_falls_back_to_english(self):
        user = _make_user("FREE")
        doc = _make_document(chars=1_000, language="xx")
        quota = _make_quota()
        db = _mock_db(quota)

        result = await PreflightService.analyze(doc, user, db)

        assert "en" in result.voice_id.lower()

    @pytest.mark.asyncio
    async def test_estimated_chapters_included(self):
        user = _make_user("FREE")
        doc = _make_document(chars=5_000, pages=75)
        quota = _make_quota()
        db = _mock_db(quota)

        result = await PreflightService.analyze(doc, user, db)

        # 75 pages → 75 // 25 = 3 chapters
        assert result.estimated_chapters == 3

    @pytest.mark.asyncio
    async def test_duration_estimation_included(self):
        user = _make_user("FREE")
        doc = _make_document(chars=14_000)  # 14_000 / 14 = 1000 sec
        quota = _make_quota()
        db = _mock_db(quota)

        result = await PreflightService.analyze(doc, user, db)

        assert 990 <= result.estimated_duration_seconds <= 1010

    @pytest.mark.asyncio
    async def test_processing_time_included(self):
        user = _make_user("FREE")
        doc = _make_document(chars=9_000)
        quota = _make_quota()
        db = _mock_db(quota)

        result = await PreflightService.analyze(doc, user, db)

        assert result.estimated_processing_minutes > 0

    @pytest.mark.asyncio
    async def test_plan_display_name_included(self):
        user = _make_user("FREE")
        doc = _make_document()
        quota = _make_quota()
        db = _mock_db(quota)

        result = await PreflightService.analyze(doc, user, db)

        assert result.plan_display_name == "Free"
        assert result.plan_tier == "FREE"


# ---------------------------------------------------------------------------
# Display maps completeness
# ---------------------------------------------------------------------------

class TestDisplayMaps:
    def test_language_display_map_covers_common_languages(self):
        for lang in ("en", "es", "fr", "de", "pt", "it"):
            assert lang in LANGUAGE_DISPLAY_MAP

    def test_voice_display_map_has_en_voice(self):
        assert "en-US-Neural2-A" in VOICE_DISPLAY_MAP

    def test_voice_display_map_values_are_human_readable(self):
        for voice_id, label in VOICE_DISPLAY_MAP.items():
            assert len(label) > 5
            assert "·" in label or "-" in label  # formatted label

"""
Unit Tests: Analytics (Phase 3.7)
==================================
Tests for:
  - DocumentClassifier.classify_document()
  - AnalyticsService.record_event() with mocked DB
  - AnalyticsService.start_session() / end_session()
  - AnalyticsService.get_completion_stats() aggregation
  - AnalyticsService.get_session_summary() aggregation
  - AnalyticsService.get_upgrade_triggers() conversion funnel
  - AnalyticsService.get_retention_signals() multi-session detection
  - AnalyticsEvent model field defaults
  - PlaybackSession model field defaults
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4
from datetime import datetime

from app.analytics.document_classifier import classify_document
from app.analytics.analytics_service import AnalyticsService, _sanitise
from app.db.models.analytics import PlaybackSession, AnalyticsEvent

pytestmark = pytest.mark.unit


# ── DocumentClassifier ────────────────────────────────────────────────────────

class TestDocumentClassifier:
    def test_unknown_returns_for_empty_inputs(self):
        assert classify_document("") == "unknown"

    def test_unknown_returns_for_generic_filename(self):
        assert classify_document("document.pdf") == "unknown"

    def test_fiction_detected_by_filename(self):
        assert classify_document("my_novel.pdf") == "fiction"

    def test_fiction_detected_by_text_sample(self):
        result = classify_document("book.pdf", "She said hello and the protagonist replied")
        assert result == "fiction"

    def test_academic_detected_by_text(self):
        result = classify_document("paper.pdf", "Abstract: methodology and hypothesis testing")
        assert result == "academic"

    def test_textbook_detected_by_keywords(self):
        result = classify_document("course.pdf", "learning objectives and key terms review questions")
        assert result == "textbook"

    def test_self_help_detected(self):
        result = classify_document("habits.pdf", "success habits mindset motivation goal setting")
        assert result == "self_help"

    def test_research_detected(self):
        result = classify_document("study.pdf", "data analysis findings research paper statistical")
        assert result == "research"

    def test_essay_detected(self):
        result = classify_document("essay.pdf", "in this essay i argue thesis statement introduction")
        assert result == "essay"

    def test_case_insensitive(self):
        result = classify_document("NOVEL.PDF", "SHE SAID HELLO TO THE PROTAGONIST")
        assert result == "fiction"

    def test_returns_highest_score_category(self):
        # Fiction signal is stronger than essay here
        result = classify_document(
            "story.pdf",
            "she said he said novel fiction narrative protagonist "
            "introduction argument"
        )
        assert result == "fiction"

    def test_filename_contributes_to_score(self):
        # "textbook" in the filename provides a strong signal
        result = classify_document("calculus_textbook.pdf")
        assert result == "textbook"


# ── Property sanitiser ────────────────────────────────────────────────────────

def test_sanitise_removes_sensitive_keys():
    props = {"plan": "PRO", "password": "s3cr3t", "token": "abc", "trigger": "quota"}
    cleaned = _sanitise(props)
    assert "password" not in cleaned
    assert "token" not in cleaned
    assert cleaned["plan"] == "PRO"
    assert cleaned["trigger"] == "quota"


def test_sanitise_empty_dict():
    assert _sanitise({}) == {}


def test_sanitise_case_insensitive():
    props = {"PASSWORD": "x", "plan": "FREE"}
    cleaned = _sanitise(props)
    assert "PASSWORD" not in cleaned
    assert cleaned["plan"] == "FREE"


# ── Model defaults ────────────────────────────────────────────────────────────

def test_playback_session_defaults():
    s = PlaybackSession()
    assert s.listened_seconds == 0
    assert s.completion_percentage == 0.0
    assert s.playback_speed == 1.0
    assert s.resumed_from_continue_listening is False


def test_analytics_event_defaults():
    e = AnalyticsEvent()
    assert e.properties == {} or e.properties is None or isinstance(e.properties, dict)


# ── AnalyticsService.record_event ─────────────────────────────────────────────

async def test_record_event_commits_to_db():
    db = AsyncMock()
    db.add = MagicMock()
    db.commit = AsyncMock()

    await AnalyticsService.record_event(
        db=db,
        user_id=uuid4(),
        event_type="paywall_viewed",
        properties={"plan": "FREE"},
    )

    db.add.assert_called_once()
    db.commit.assert_awaited_once()


async def test_record_event_silently_handles_db_error():
    db = AsyncMock()
    db.add = MagicMock()
    db.commit = AsyncMock(side_effect=Exception("DB unavailable"))
    db.rollback = AsyncMock()

    # Should not raise
    await AnalyticsService.record_event(
        db=db,
        user_id=uuid4(),
        event_type="audiobook_completed",
        properties={},
    )
    db.rollback.assert_awaited_once()


async def test_record_event_strips_sensitive_props():
    db = AsyncMock()
    db.add = MagicMock()
    db.commit = AsyncMock()
    added_event: AnalyticsEvent | None = None

    def capture_add(obj):
        nonlocal added_event
        added_event = obj

    db.add.side_effect = capture_add

    await AnalyticsService.record_event(
        db=db,
        user_id=uuid4(),
        event_type="upgrade_clicked",
        properties={"plan": "PRO", "password": "oops", "trigger": "quota_exceeded"},
    )

    assert added_event is not None
    assert "password" not in added_event.properties
    assert added_event.properties["plan"] == "PRO"
    assert added_event.properties["trigger"] == "quota_exceeded"


# ── AnalyticsService.start_session ────────────────────────────────────────────

async def test_start_session_returns_session_id():
    db = AsyncMock()
    db.add = MagicMock()
    db.commit = AsyncMock()

    created_session = PlaybackSession()
    import uuid
    created_session.id = uuid.uuid4()

    async def mock_refresh(obj):
        obj.id = created_session.id

    db.refresh = mock_refresh

    session_id = await AnalyticsService.start_session(
        db=db,
        user_id=uuid4(),
        document_id=uuid4(),
        source="direct",
        resumed_from_continue_listening=False,
    )

    assert session_id is not None
    db.add.assert_called_once()
    db.commit.assert_awaited_once()


async def test_start_session_returns_none_on_error():
    db = AsyncMock()
    db.add = MagicMock()
    db.commit = AsyncMock(side_effect=Exception("DB error"))
    db.rollback = AsyncMock()

    result = await AnalyticsService.start_session(
        db=db,
        user_id=uuid4(),
        document_id=None,
        source="autoplay",
    )

    assert result is None
    db.rollback.assert_awaited_once()


# ── AnalyticsService.end_session ──────────────────────────────────────────────

async def test_end_session_updates_session_fields():
    existing = PlaybackSession()
    existing.id = uuid4()
    existing.user_id = uuid4()
    existing.document_id = uuid4()
    existing.listened_seconds = 0
    existing.completion_percentage = 0.0

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = existing

    db = AsyncMock()
    db.execute = AsyncMock(return_value=mock_result)
    db.commit = AsyncMock()

    await AnalyticsService.end_session(
        db=db,
        session_id=existing.id,
        listened_seconds=420,
        completion_percentage=85.0,
        playback_speed=1.25,
        chapters_visited=[0, 1, 2],
    )

    assert existing.listened_seconds == 420
    assert existing.completion_percentage == 85.0
    assert existing.playback_speed == 1.25
    assert existing.chapters_visited == [0, 1, 2]
    assert existing.ended_at is not None
    db.commit.assert_awaited_once()


async def test_end_session_clamps_completion_percentage():
    existing = PlaybackSession()
    existing.id = uuid4()

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = existing

    db = AsyncMock()
    db.execute = AsyncMock(return_value=mock_result)
    db.commit = AsyncMock()

    await AnalyticsService.end_session(
        db=db,
        session_id=existing.id,
        listened_seconds=999,
        completion_percentage=150.0,  # should be clamped to 100
    )

    assert existing.completion_percentage == 100.0


async def test_end_session_handles_missing_session():
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None

    db = AsyncMock()
    db.execute = AsyncMock(return_value=mock_result)
    db.commit = AsyncMock()

    # Should not raise
    await AnalyticsService.end_session(
        db=db,
        session_id=uuid4(),
        listened_seconds=60,
        completion_percentage=20.0,
    )
    db.commit.assert_not_awaited()


# ── AnalyticsService.get_completion_stats ─────────────────────────────────────

async def test_get_completion_stats_calculates_rates():
    mock_row = MagicMock()
    mock_row.total_sessions = 100
    mock_row.avg_completion_pct = 45.0
    mock_row.avg_listened_seconds = 900.0
    mock_row.engaged_count = 80   # 80%
    mock_row.halfway_count = 55   # 55%
    mock_row.completed_count = 30 # 30%

    mock_result = MagicMock()
    mock_result.one.return_value = mock_row

    db = AsyncMock()
    db.execute = AsyncMock(return_value=mock_result)

    stats = await AnalyticsService.get_completion_stats(db, days=30)

    assert stats["total_sessions"] == 100
    assert stats["engaged_rate_pct"] == 80.0
    assert stats["halfway_rate_pct"] == 55.0
    assert stats["completed_rate_pct"] == 30.0
    assert stats["avg_completion_pct"] == 45.0


async def test_get_completion_stats_handles_zero_sessions():
    mock_row = MagicMock()
    mock_row.total_sessions = 0
    mock_row.avg_completion_pct = None
    mock_row.avg_listened_seconds = None
    mock_row.engaged_count = 0
    mock_row.halfway_count = 0
    mock_row.completed_count = 0

    mock_result = MagicMock()
    mock_result.one.return_value = mock_row

    db = AsyncMock()
    db.execute = AsyncMock(return_value=mock_result)

    stats = await AnalyticsService.get_completion_stats(db, days=30)

    assert stats["total_sessions"] == 0
    assert stats["engaged_rate_pct"] == 0.0
    assert stats["halfway_rate_pct"] == 0.0
    assert stats["completed_rate_pct"] == 0.0


# ── AnalyticsService.get_upgrade_triggers ─────────────────────────────────────

async def test_get_upgrade_triggers_calculates_funnel():
    call_count = 0

    async def mock_execute(stmt):
        nonlocal call_count
        call_count += 1
        mock_result = MagicMock()
        if call_count == 1:
            mock_result.scalar.return_value = 200   # paywall views
        elif call_count == 2:
            mock_result.scalar.return_value = 40    # upgrade clicks
        else:
            mock_result.scalar.return_value = 10    # conversions
        return mock_result

    db = AsyncMock()
    db.execute = mock_execute

    result = await AnalyticsService.get_upgrade_triggers(db, days=90)

    assert result["paywall_views"] == 200
    assert result["upgrade_clicks"] == 40
    assert result["conversions"] == 10
    assert result["paywall_click_rate"] == pytest.approx(20.0)   # 40/200 × 100
    assert result["click_convert_rate"] == pytest.approx(25.0)  # 10/40 × 100


async def test_get_upgrade_triggers_zero_views():
    async def mock_execute(stmt):
        mock_result = MagicMock()
        mock_result.scalar.return_value = 0
        return mock_result

    db = AsyncMock()
    db.execute = mock_execute

    result = await AnalyticsService.get_upgrade_triggers(db, days=30)

    assert result["paywall_click_rate"] == 0.0
    assert result["click_convert_rate"] == 0.0


# ── AnalyticsService.get_retention_signals ────────────────────────────────────

async def test_get_retention_signals_calculates_rate():
    mock_row = MagicMock()
    mock_row.total_users = 50
    mock_row.returning_users = 20   # 40% retention
    mock_row.avg_sessions = 2.4

    mock_result = MagicMock()
    mock_result.one.return_value = mock_row

    db = AsyncMock()
    db.execute = AsyncMock(return_value=mock_result)

    signals = await AnalyticsService.get_retention_signals(db)

    assert signals["total_users_with_sessions"] == 50
    assert signals["returning_users"] == 20
    assert signals["retention_rate_pct"] == pytest.approx(40.0)
    assert signals["avg_sessions_per_user"] == pytest.approx(2.4)


async def test_get_retention_signals_no_users():
    mock_row = MagicMock()
    mock_row.total_users = 0
    mock_row.returning_users = 0
    mock_row.avg_sessions = None

    mock_result = MagicMock()
    mock_result.one.return_value = mock_row

    db = AsyncMock()
    db.execute = AsyncMock(return_value=mock_result)

    signals = await AnalyticsService.get_retention_signals(db)

    assert signals["retention_rate_pct"] == 0.0
    assert signals["avg_sessions_per_user"] == 0.0

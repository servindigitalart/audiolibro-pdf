"""
Unit Tests: Cost Telemetry (Phase 3.6)
=======================================
Tests for:
  - UnitEconomicsEngine.listening_hours_for_chars()
  - UnitEconomicsEngine.cost_per_listening_hour()
  - CostTracker.get_plan_economics() (mocked DB)
  - CostTracker.get_expensive_jobs() (mocked DB)
  - AbuseDetector.check_generation_abuse() and tracking helpers
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4
from datetime import datetime

from tests.fakes import FakeRedis
from app.pricing.tiers import PlanTier
from app.pricing.unit_economics import UnitEconomicsEngine, CHARS_PER_LISTENING_HOUR
from app.financial.abuse.abuse_detector import AbuseDetector, AbusePattern, AbuseSeverity

pytestmark = pytest.mark.unit


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def engine():
    return UnitEconomicsEngine()


@pytest.fixture
def redis():
    return FakeRedis()


@pytest.fixture
def mock_db():
    return AsyncMock()


@pytest.fixture
def detector(redis, mock_db):
    return AbuseDetector(db=mock_db, redis=redis)


# ── CHARS_PER_LISTENING_HOUR constant ─────────────────────────────────────────

def test_chars_per_listening_hour_constant():
    assert CHARS_PER_LISTENING_HOUR == 50_000


# ── listening_hours_for_chars ─────────────────────────────────────────────────

def test_listening_hours_zero_chars(engine):
    assert engine.listening_hours_for_chars(0) == 0.0


def test_listening_hours_one_hour(engine):
    assert engine.listening_hours_for_chars(50_000) == pytest.approx(1.0)


def test_listening_hours_half_hour(engine):
    assert engine.listening_hours_for_chars(25_000) == pytest.approx(0.5)


def test_listening_hours_large_book(engine):
    # 500K chars = 10 hours
    assert engine.listening_hours_for_chars(500_000) == pytest.approx(10.0)


def test_listening_hours_is_static_method():
    # Should be callable without an instance
    result = UnitEconomicsEngine.listening_hours_for_chars(100_000)
    assert result == pytest.approx(2.0)


# ── cost_per_listening_hour ───────────────────────────────────────────────────

def test_cost_per_listening_hour_standard_tiers(engine):
    # FREE and BASIC use standard TTS: $0.000004 × 50_000 = $0.20/hr
    for tier in (PlanTier.FREE, PlanTier.BASIC):
        cost = engine.cost_per_listening_hour(tier)
        assert cost == pytest.approx(0.20), f"Unexpected cost for {tier}: {cost}"


def test_cost_per_listening_hour_neural_tiers(engine):
    # PRO and ENTERPRISE use neural TTS: $0.000016 × 50_000 = $0.80/hr
    for tier in (PlanTier.PRO, PlanTier.ENTERPRISE):
        cost = engine.cost_per_listening_hour(tier)
        assert cost == pytest.approx(0.80), f"Unexpected cost for {tier}: {cost}"


def test_cost_per_listening_hour_neural_is_4x_standard(engine):
    standard = engine.cost_per_listening_hour(PlanTier.BASIC)
    neural = engine.cost_per_listening_hour(PlanTier.PRO)
    assert neural == pytest.approx(standard * 4)


# ── ProcessingJob telemetry fields ────────────────────────────────────────────

def test_processing_job_has_telemetry_fields():
    from app.db.models.processing_job import ProcessingJob
    job = ProcessingJob()
    assert hasattr(job, "characters_processed")
    assert hasattr(job, "estimated_cost_usd")
    assert hasattr(job, "plan_tier_at_generation")
    # All three are nullable by default
    assert job.characters_processed is None
    assert job.estimated_cost_usd is None
    assert job.plan_tier_at_generation is None


# ── AbuseDetector.check_generation_abuse — repeated regeneration ──────────────

async def test_no_abuse_when_redis_empty(detector):
    result = await detector.check_generation_abuse(
        user_id=uuid4(),
        document_id="doc-abc",
        chars_requested=1000,
    )
    assert result is None


async def test_repeated_regeneration_detected(detector):
    user_id = uuid4()
    doc_id = "doc-regen"
    # Simulate 5 previous regenerations
    for _ in range(5):
        await detector.track_generation(user_id, doc_id, chars=5_000)

    result = await detector.check_generation_abuse(
        user_id=user_id,
        document_id=doc_id,
        chars_requested=5_000,
        regen_threshold=5,
    )
    assert result is not None
    assert result["pattern"] == AbusePattern.REPEATED_REGENERATION
    assert result["regen_count"] == 5
    assert result["document_id"] == doc_id


async def test_repeated_regeneration_below_threshold_is_clean(detector):
    user_id = uuid4()
    doc_id = "doc-ok"
    for _ in range(3):
        await detector.track_generation(user_id, doc_id, chars=5_000)

    result = await detector.check_generation_abuse(
        user_id=user_id,
        document_id=doc_id,
        chars_requested=5_000,
        regen_threshold=5,
    )
    assert result is None


# ── AbuseDetector.check_generation_abuse — large PDF repeated ────────────────

async def test_large_pdf_repeated_detected(detector):
    user_id = uuid4()
    doc_id = "doc-large"
    # Track 2 regenerations of a large PDF
    for _ in range(2):
        await detector.track_generation(user_id, doc_id, chars=250_000)

    result = await detector.check_generation_abuse(
        user_id=user_id,
        document_id=doc_id,
        chars_requested=250_000,
        large_pdf_chars=200_000,
    )
    assert result is not None
    assert result["pattern"] == AbusePattern.LARGE_PDF_REPEATED
    assert result["chars_requested"] == 250_000


async def test_small_pdf_repeated_does_not_trigger_large_pdf_pattern(detector):
    user_id = uuid4()
    doc_id = "doc-small"
    for _ in range(3):
        await detector.track_generation(user_id, doc_id, chars=50_000)

    result = await detector.check_generation_abuse(
        user_id=user_id,
        document_id=doc_id,
        chars_requested=50_000,
        large_pdf_chars=200_000,
    )
    assert result is None


# ── AbuseDetector.check_generation_abuse — mass retry ────────────────────────

async def test_mass_retry_detected(detector):
    user_id = uuid4()
    for _ in range(10):
        await detector.track_job_retry(user_id)

    result = await detector.check_generation_abuse(
        user_id=user_id,
        document_id=None,
        chars_requested=0,
        retry_threshold=10,
    )
    assert result is not None
    assert result["pattern"] == AbusePattern.MASS_RETRY
    assert result["retry_count"] == 10


async def test_mass_retry_below_threshold_is_clean(detector):
    user_id = uuid4()
    for _ in range(5):
        await detector.track_job_retry(user_id)

    result = await detector.check_generation_abuse(
        user_id=user_id,
        document_id=None,
        chars_requested=0,
        retry_threshold=10,
    )
    assert result is None


# ── AbuseDetector severity scoring ───────────────────────────────────────────

async def test_high_regen_count_produces_high_severity(detector):
    user_id = uuid4()
    doc_id = "doc-sev"
    # 50 regenerations → ratio = 10× threshold → CRITICAL
    for _ in range(50):
        await detector.track_generation(user_id, doc_id, chars=1_000)

    result = await detector.check_generation_abuse(
        user_id=user_id,
        document_id=doc_id,
        chars_requested=1_000,
        regen_threshold=5,
    )
    assert result is not None
    assert result["severity"] in (AbuseSeverity.HIGH, AbuseSeverity.CRITICAL)


# ── CostTracker.get_plan_economics — mocked DB ───────────────────────────────

async def test_get_plan_economics_returns_list():
    from app.financial.cost.cost_tracker import CostTracker

    mock_row = MagicMock()
    mock_row.plan_tier = "PRO"
    mock_row.job_count = 42
    mock_row.avg_cost_usd = 0.0045
    mock_row.total_cost_usd = 0.189
    mock_row.avg_chars = 150_000

    mock_result = MagicMock()
    mock_result.all.return_value = [mock_row]

    db = AsyncMock()
    db.execute = AsyncMock(return_value=mock_result)

    rows = await CostTracker.get_plan_economics(db)
    assert isinstance(rows, list)
    assert len(rows) == 1
    assert rows[0]["plan_tier"] == "PRO"
    assert rows[0]["job_count"] == 42
    assert rows[0]["avg_chars"] == 150_000


async def test_get_plan_economics_empty_db():
    from app.financial.cost.cost_tracker import CostTracker

    mock_result = MagicMock()
    mock_result.all.return_value = []

    db = AsyncMock()
    db.execute = AsyncMock(return_value=mock_result)

    rows = await CostTracker.get_plan_economics(db)
    assert rows == []


# ── CostTracker.get_expensive_jobs — mocked DB ───────────────────────────────

async def test_get_expensive_jobs_returns_list():
    from app.financial.cost.cost_tracker import CostTracker

    mock_row = MagicMock()
    mock_row.job_id = uuid4()
    mock_row.document_id = uuid4()
    mock_row.user_id = uuid4()
    mock_row.estimated_cost_usd = 0.312
    mock_row.characters_processed = 400_000
    mock_row.plan_tier_at_generation = "ENTERPRISE"
    mock_row.completed_at = datetime(2026, 5, 27, 12, 0, 0)

    mock_result = MagicMock()
    # get_expensive_jobs iterates over the result directly
    mock_result.__iter__ = MagicMock(return_value=iter([mock_row]))

    db = AsyncMock()
    db.execute = AsyncMock(return_value=mock_result)

    jobs = await CostTracker.get_expensive_jobs(db, limit=5, days=30)
    assert isinstance(jobs, list)
    assert len(jobs) == 1
    assert jobs[0]["plan_tier"] == "ENTERPRISE"
    assert jobs[0]["estimated_cost_usd"] == pytest.approx(0.312)


# ── CostTracker.track_event — logger kwargs style (no TypeError) ──────────────

async def test_track_event_returns_cost_event():
    """Proves BoundLogger kwargs call doesn't raise TypeError."""
    from app.financial.cost.cost_tracker import CostTracker
    from app.financial.cost.cost_enums import CostEventType, CostProvider
    from app.financial.cost.cost_models import CostEvent

    user_id = uuid4()
    db = AsyncMock()
    db.add = MagicMock()  # sync method on AsyncSession

    event = await CostTracker.track_event(
        db,
        user_id=user_id,
        event_type=CostEventType.TTS_JOB,
        quantity=50_000.0,
        unit_cost=0.000016,
        provider=CostProvider.GOOGLE,
    )

    assert isinstance(event, CostEvent)
    assert event.user_id == user_id
    assert event.event_type == CostEventType.TTS_JOB
    assert event.total_cost == pytest.approx(50_000.0 * 0.000016)
    db.add.assert_called_once_with(event)
    db.commit.assert_awaited_once()


async def test_track_event_defaults():
    """provider defaults to INTERNAL, metadata to empty dict."""
    from app.financial.cost.cost_tracker import CostTracker
    from app.financial.cost.cost_enums import CostEventType, CostProvider
    from app.financial.cost.cost_models import CostEvent

    db = AsyncMock()
    db.add = MagicMock()

    event = await CostTracker.track_event(
        db,
        user_id=uuid4(),
        event_type=CostEventType.API_CALL,
    )

    assert isinstance(event, CostEvent)
    assert event.provider == CostProvider.INTERNAL
    assert event.activity_metadata == {}
    assert event.total_cost == pytest.approx(0.0)  # quantity=1.0, unit_cost=0.0

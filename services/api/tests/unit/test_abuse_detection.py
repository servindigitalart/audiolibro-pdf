"""
Unit Tests: AbuseDetector
==========================
Tests for Redis-backed abuse detection patterns.

DB-dependent checks (usage_spike, cost_spike) require CostEvent rows
and are covered in integration tests.  Here we test:
  - failed-login tracking and threshold detection
  - excessive API call detection (Redis counter based)
  - severity scoring logic
  - result payload structure
"""
import pytest
from unittest.mock import AsyncMock
from uuid import uuid4

from tests.fakes import FakeRedis
from app.financial.abuse.abuse_detector import (
    AbuseDetector,
    AbusePattern,
    AbuseSeverity,
)

pytestmark = pytest.mark.unit


@pytest.fixture
def redis() -> FakeRedis:
    return FakeRedis()


@pytest.fixture
def mock_db():
    return AsyncMock()


@pytest.fixture
def detector(redis: FakeRedis, mock_db) -> AbuseDetector:
    return AbuseDetector(db=mock_db, redis=redis)


# ── Failed login tracking ─────────────────────────────────────────────────────

async def test_no_failed_logins_returns_none(detector):
    result = await detector.check_failed_logins("user@example.com")
    assert result is None


async def test_track_failed_login_increments_counter(detector, redis):
    email = "track@example.com"
    await detector.track_failed_login(email)
    await detector.track_failed_login(email)

    key = f"abuse:failed_login:{email}"
    count = await redis.get(key)
    assert int(count) == 2


async def test_below_threshold_does_not_detect(detector):
    email = "below@example.com"
    for _ in range(4):
        await detector.track_failed_login(email)
    result = await detector.check_failed_logins(email, threshold=5)
    assert result is None


async def test_at_threshold_detects_pattern(detector):
    email = "at@example.com"
    for _ in range(5):
        await detector.track_failed_login(email)
    result = await detector.check_failed_logins(email, threshold=5)
    assert result is not None
    assert result["pattern"] == AbusePattern.EXCESSIVE_FAILED_LOGINS


async def test_above_threshold_reports_actual_count(detector):
    email = "over@example.com"
    for _ in range(10):
        await detector.track_failed_login(email)
    result = await detector.check_failed_logins(email, threshold=5)
    assert result["failed_attempts"] == 10


async def test_reset_clears_failed_login_state(detector):
    email = "reset@example.com"
    for _ in range(5):
        await detector.track_failed_login(email)
    await detector.reset_failed_logins(email)
    result = await detector.check_failed_logins(email, threshold=5)
    assert result is None


async def test_different_identifiers_tracked_independently(detector):
    email_a = "a@example.com"
    email_b = "b@example.com"
    for _ in range(5):
        await detector.track_failed_login(email_a)
    # b has no failures
    result = await detector.check_failed_logins(email_b, threshold=5)
    assert result is None


async def test_detection_result_contains_required_fields(detector):
    email = "fields@example.com"
    for _ in range(6):
        await detector.track_failed_login(email)
    result = await detector.check_failed_logins(email, threshold=5)
    required = {"pattern", "severity", "user_identifier", "failed_attempts",
                "threshold", "window_minutes", "detected_at"}
    assert required.issubset(result.keys())


async def test_detection_result_user_identifier_matches_input(detector):
    email = "match@example.com"
    for _ in range(6):
        await detector.track_failed_login(email)
    result = await detector.check_failed_logins(email, threshold=5)
    assert result["user_identifier"] == email


# ── Excessive API call detection ──────────────────────────────────────────────

async def test_no_api_calls_tracked_returns_none(detector):
    result = await detector.check_excessive_api_calls(uuid4(), threshold=1000)
    assert result is None


async def test_api_calls_below_threshold_returns_none(detector, redis):
    user_id = uuid4()
    await redis.set(f"abuse:api_calls:{user_id}:60m", "500")
    result = await detector.check_excessive_api_calls(
        user_id, lookback_minutes=60, threshold=1000
    )
    assert result is None


async def test_api_calls_at_threshold_detects(detector, redis):
    user_id = uuid4()
    await redis.set(f"abuse:api_calls:{user_id}:60m", "1000")
    result = await detector.check_excessive_api_calls(
        user_id, lookback_minutes=60, threshold=1000
    )
    assert result is not None
    assert result["pattern"] == AbusePattern.EXCESSIVE_API_CALLS
    assert result["api_calls"] == 1000


async def test_api_calls_above_threshold_detects(detector, redis):
    user_id = uuid4()
    await redis.set(f"abuse:api_calls:{user_id}:60m", "5000")
    result = await detector.check_excessive_api_calls(
        user_id, lookback_minutes=60, threshold=1000
    )
    assert result is not None
    assert result["api_calls"] == 5000


# ── Severity scoring ──────────────────────────────────────────────────────────

def test_severity_just_above_threshold_is_low(detector):
    assert detector._calculate_severity(actual=5, threshold=5) == AbuseSeverity.LOW


def test_severity_at_2x_threshold_is_medium(detector):
    assert detector._calculate_severity(actual=10, threshold=5) == AbuseSeverity.MEDIUM


def test_severity_at_5x_threshold_is_high(detector):
    assert detector._calculate_severity(actual=25, threshold=5) == AbuseSeverity.HIGH


def test_severity_at_10x_threshold_is_critical(detector):
    assert detector._calculate_severity(actual=50, threshold=5) == AbuseSeverity.CRITICAL


def test_spike_severity_below_5x_is_low(detector):
    assert detector._calculate_spike_severity(4.9) == AbuseSeverity.LOW


def test_spike_severity_at_5x_is_medium(detector):
    assert detector._calculate_spike_severity(5.0) == AbuseSeverity.MEDIUM


def test_spike_severity_at_10x_is_high(detector):
    assert detector._calculate_spike_severity(10.0) == AbuseSeverity.HIGH


def test_spike_severity_at_20x_is_critical(detector):
    assert detector._calculate_spike_severity(20.0) == AbuseSeverity.CRITICAL

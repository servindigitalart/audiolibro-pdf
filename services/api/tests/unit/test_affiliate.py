"""
Unit Tests: Affiliate / Referral System (Phase 5A)
====================================================
Tests for:
  - Affiliate creation and slug validation
  - Referral code validation (active/paused/missing)
  - Signup attribution (active affiliate only, no overwrite)
  - Stripe conversion recording with idempotency
  - Commission calculation
  - Payout status transitions (pending → approved → paid)
  - Conversion reversal
  - Invalid / paused affiliate handling
  - get_stats aggregation
  - _slugify helper
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from app.affiliate.affiliate_service import AffiliateService, _slugify, _hash, VALID_STATUSES

pytestmark = pytest.mark.unit


# ── _slugify helper ───────────────────────────────────────────────────────────

def test_slugify_basic():
    assert _slugify("John Smith") == "john-smith"


def test_slugify_special_chars():
    assert _slugify("AI Tools & More!") == "ai-tools-more"


def test_slugify_truncates_long():
    assert len(_slugify("a" * 100)) <= 50


def test_slugify_lowercase():
    assert _slugify("UPPERCASE") == "uppercase"


# ── _hash helper ──────────────────────────────────────────────────────────────

def test_hash_is_64_chars():
    assert len(_hash("192.168.1.1")) == 64


def test_hash_deterministic():
    assert _hash("test-ua") == _hash("test-ua")


def test_hash_different_inputs():
    assert _hash("a") != _hash("b")


# ── is_active_slug ────────────────────────────────────────────────────────────

async def test_is_active_slug_returns_true_for_active():
    active_aff = MagicMock()
    active_aff.status = "active"

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = active_aff

    db = AsyncMock()
    db.execute = AsyncMock(return_value=mock_result)

    assert await AffiliateService.is_active_slug(db, "mycode") is True


async def test_is_active_slug_returns_false_for_paused():
    paused_aff = MagicMock()
    paused_aff.status = "paused"

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = paused_aff

    db = AsyncMock()
    db.execute = AsyncMock(return_value=mock_result)

    assert await AffiliateService.is_active_slug(db, "paused-code") is False


async def test_is_active_slug_returns_false_for_missing():
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None

    db = AsyncMock()
    db.execute = AsyncMock(return_value=mock_result)

    assert await AffiliateService.is_active_slug(db, "nonexistent") is False


# ── create_affiliate ──────────────────────────────────────────────────────────

async def test_create_affiliate_success():
    mock_aff = MagicMock()
    mock_aff.id   = uuid4()
    mock_aff.slug = "test-creator"

    existing_result = MagicMock()
    existing_result.scalar_one_or_none.return_value = None  # slug not taken

    db = AsyncMock()
    db.execute = AsyncMock(return_value=existing_result)
    db.add     = MagicMock()
    db.commit  = AsyncMock()
    db.refresh = AsyncMock()

    aff = await AffiliateService.create_affiliate(
        db, name="Test Creator", email="creator@example.com", slug="test-creator"
    )

    db.add.assert_called_once()
    db.commit.assert_awaited_once()


async def test_create_affiliate_invalid_slug_raises():
    db = AsyncMock()
    with pytest.raises(ValueError, match="Invalid slug"):
        await AffiliateService.create_affiliate(
            db, name="Bad", email="bad@example.com", slug="AB"  # too short + uppercase
        )


async def test_create_affiliate_autogenerates_slug():
    existing_result = MagicMock()
    existing_result.scalar_one_or_none.return_value = None

    db = AsyncMock()
    db.execute = AsyncMock(return_value=existing_result)
    db.add     = MagicMock()
    db.commit  = AsyncMock()
    db.refresh = AsyncMock()

    # No slug provided — should auto-generate from name
    await AffiliateService.create_affiliate(
        db, name="Alice Blogger", email="alice@blog.com"
    )

    db.add.assert_called_once()
    created_obj = db.add.call_args[0][0]
    assert created_obj.slug == "alice-blogger"


# ── attribute_signup ──────────────────────────────────────────────────────────

async def test_attribute_signup_active_affiliate_succeeds():
    aff = MagicMock()
    aff.id     = uuid4()
    aff.status = "active"

    lookup_result  = MagicMock()
    lookup_result.scalar_one_or_none.return_value = aff

    db = AsyncMock()
    db.execute = AsyncMock(return_value=lookup_result)
    db.commit  = AsyncMock()

    result = await AffiliateService.attribute_signup(db, uuid4(), "active-slug")
    assert result is True


async def test_attribute_signup_paused_affiliate_fails():
    paused_aff = MagicMock()
    paused_aff.status = "paused"

    lookup_result = MagicMock()
    lookup_result.scalar_one_or_none.return_value = paused_aff

    db = AsyncMock()
    db.execute = AsyncMock(return_value=lookup_result)

    result = await AffiliateService.attribute_signup(db, uuid4(), "paused-slug")
    assert result is False


async def test_attribute_signup_missing_slug_fails():
    lookup_result = MagicMock()
    lookup_result.scalar_one_or_none.return_value = None

    db = AsyncMock()
    db.execute = AsyncMock(return_value=lookup_result)

    result = await AffiliateService.attribute_signup(db, uuid4(), "bad-slug")
    assert result is False


async def test_attribute_signup_db_error_returns_false():
    db = AsyncMock()
    db.execute = AsyncMock(side_effect=Exception("DB error"))
    db.rollback = AsyncMock()

    result = await AffiliateService.attribute_signup(db, uuid4(), "any-slug")
    assert result is False
    db.rollback.assert_awaited_once()


# ── record_conversion ─────────────────────────────────────────────────────────

async def _make_conversion_db(affiliate_id, commission_rate=20.0):
    """Helper: return a mocked DB that simulates a user with referred_by set."""
    aff = MagicMock()
    aff.id                 = affiliate_id
    aff.commission_rate_pct = commission_rate

    # First execute: user lookup → returns affiliate_id UUID
    user_row    = MagicMock()
    user_row.scalar_one_or_none.return_value = affiliate_id

    # Second execute: affiliate lookup → returns aff
    aff_row     = MagicMock()
    aff_row.scalar_one_or_none.return_value = aff

    execute_call = 0

    async def mock_execute(stmt):
        nonlocal execute_call
        execute_call += 1
        return user_row if execute_call == 1 else aff_row

    db = AsyncMock()
    db.execute = mock_execute
    db.add     = MagicMock()
    db.commit  = AsyncMock()
    db.refresh = AsyncMock()
    db.rollback = AsyncMock()
    return db


async def test_record_conversion_creates_row():
    affiliate_id = uuid4()
    db = await _make_conversion_db(affiliate_id, commission_rate=20.0)

    result = await AffiliateService.record_conversion(
        db,
        user_id=uuid4(),
        stripe_event_id="evt_123",
        stripe_customer_id="cus_abc",
        stripe_subscription_id="sub_xyz",
        plan_tier="PRO",
        amount_usd=29.0,
    )

    db.add.assert_called_once()
    created = db.add.call_args[0][0]
    assert created.stripe_event_id    == "evt_123"
    assert created.plan_tier          == "PRO"
    assert created.amount_usd         == 29.0
    assert created.commission_pct     == 20.0
    assert created.commission_amount_usd == pytest.approx(5.8, abs=0.001)
    assert created.status             == "pending"


async def test_record_conversion_commission_calculation():
    """Commission = amount × rate / 100, rounded to 4dp."""
    affiliate_id = uuid4()
    db = await _make_conversion_db(affiliate_id, commission_rate=25.0)

    await AffiliateService.record_conversion(
        db,
        user_id=uuid4(),
        stripe_event_id="evt_comm_test",
        stripe_customer_id=None,
        stripe_subscription_id=None,
        plan_tier="BASIC",
        amount_usd=9.0,
    )

    created = db.add.call_args[0][0]
    # 9.00 × 25% = $2.25
    assert created.commission_amount_usd == pytest.approx(2.25, abs=0.001)


async def test_record_conversion_no_attribution_returns_none():
    """User without referred_by_affiliate_id → no conversion row."""
    user_row = MagicMock()
    user_row.scalar_one_or_none.return_value = None  # no affiliate linked

    db = AsyncMock()
    db.execute  = AsyncMock(return_value=user_row)
    db.rollback = AsyncMock()

    result = await AffiliateService.record_conversion(
        db,
        user_id=uuid4(),
        stripe_event_id="evt_no_aff",
        stripe_customer_id=None,
        stripe_subscription_id=None,
        plan_tier="PRO",
        amount_usd=29.0,
    )

    assert result is None


async def test_record_conversion_idempotent_on_integrity_error():
    """Duplicate stripe_event_id → IntegrityError → returns None silently."""
    from sqlalchemy.exc import IntegrityError

    aff_id = uuid4()
    user_row = MagicMock()
    user_row.scalar_one_or_none.return_value = aff_id

    aff = MagicMock()
    aff.id = aff_id
    aff.commission_rate_pct = 20.0

    aff_row = MagicMock()
    aff_row.scalar_one_or_none.return_value = aff

    execute_call = 0
    async def mock_execute(stmt):
        nonlocal execute_call
        execute_call += 1
        return user_row if execute_call == 1 else aff_row

    db = AsyncMock()
    db.execute  = mock_execute
    db.add      = MagicMock()
    db.commit   = AsyncMock(side_effect=IntegrityError("dup", None, None))
    db.rollback = AsyncMock()

    result = await AffiliateService.record_conversion(
        db,
        user_id=uuid4(),
        stripe_event_id="evt_duplicate",
        stripe_customer_id=None,
        stripe_subscription_id=None,
        plan_tier="PRO",
        amount_usd=29.0,
    )

    assert result is None
    db.rollback.assert_awaited_once()


# ── Status transitions ────────────────────────────────────────────────────────

async def _make_conv(status="pending"):
    conv = MagicMock()
    conv.id                   = uuid4()
    conv.status               = status
    conv.commission_amount_usd = 5.8
    conv.affiliate_id         = uuid4()

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = conv

    db = AsyncMock()
    db.execute = AsyncMock(return_value=mock_result)
    db.commit  = AsyncMock()
    db.refresh = AsyncMock()
    return db, conv


async def test_approve_conversion_sets_status():
    db, conv = await _make_conv("pending")
    result = await AffiliateService.approve_conversion(db, conv.id)
    assert conv.status == "approved"
    db.commit.assert_awaited_once()


async def test_mark_payout_paid_sets_status():
    db, conv = await _make_conv("approved")
    result = await AffiliateService.mark_payout_paid(db, conv.id)
    assert conv.status == "paid"
    db.commit.assert_awaited_once()


async def test_reverse_conversion_sets_status():
    db, conv = await _make_conv("pending")
    result = await AffiliateService.reverse_conversion(db, conv.id)
    assert conv.status == "reversed"
    db.commit.assert_awaited_once()


async def test_transition_missing_conversion_returns_none():
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None

    db = AsyncMock()
    db.execute = AsyncMock(return_value=mock_result)

    result = await AffiliateService.approve_conversion(db, uuid4())
    assert result is None


# ── get_stats ─────────────────────────────────────────────────────────────────

async def test_get_stats_returns_expected_shape():
    # get_stats calls db.scalar() for clicks and signups,
    # then db.execute() for the grouped conv_rows.
    conv_rows = [
        MagicMock(__getitem__=lambda s, i: ["pending", 2, 10.0][i]),
        MagicMock(__getitem__=lambda s, i: ["paid",    1,  5.0][i]),
    ]
    mock_conv_result = MagicMock()
    mock_conv_result.all.return_value = conv_rows

    db = AsyncMock()
    db.scalar  = AsyncMock(side_effect=[10, 3])        # clicks, signups
    db.execute = AsyncMock(return_value=mock_conv_result)

    stats = await AffiliateService.get_stats(db, uuid4())

    assert stats["clicks"]  == 10
    assert stats["signups"] == 3
    assert "conversions_total"       in stats
    assert "commission_pending_usd"  in stats
    assert "commission_paid_usd"     in stats


async def test_get_stats_zero_state():
    mock_conv_result = MagicMock()
    mock_conv_result.all.return_value = []

    db = AsyncMock()
    db.scalar  = AsyncMock(return_value=0)
    db.execute = AsyncMock(return_value=mock_conv_result)

    stats = await AffiliateService.get_stats(db, uuid4())

    assert stats["clicks"]  == 0
    assert stats["signups"] == 0
    assert stats["commission_pending_usd"] == 0.0
    assert stats["commission_paid_usd"]    == 0.0


# ── track_click ───────────────────────────────────────────────────────────────

async def test_track_click_hashes_ip_and_ua():
    db = AsyncMock()
    db.add    = MagicMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()

    await AffiliateService.track_click(
        db,
        affiliate_id=uuid4(),
        visitor_id="vis-123",
        landing_path="/",
        raw_user_agent="Mozilla/5.0",
        raw_ip="1.2.3.4",
    )

    db.add.assert_called_once()
    click_obj = db.add.call_args[0][0]

    # Should store hashes, not raw values
    assert click_obj.user_agent_hash is not None
    assert click_obj.ip_hash         is not None
    assert "Mozilla" not in (click_obj.user_agent_hash or "")
    assert "1.2.3.4" not in (click_obj.ip_hash or "")
    assert len(click_obj.user_agent_hash) == 64   # SHA-256 hex digest


async def test_track_click_db_error_does_not_raise():
    db = AsyncMock()
    db.add    = MagicMock()
    db.commit = AsyncMock(side_effect=Exception("DB error"))
    db.rollback = AsyncMock()

    # Should not raise
    await AffiliateService.track_click(db, affiliate_id=uuid4())


# ── Admin route dependency check ──────────────────────────────────────────────

def test_admin_affiliates_router_requires_admin():
    from app.routers.admin_affiliates import router
    from app.core.auth_dependencies import require_admin
    from fastapi.routing import APIRoute

    for route in router.routes:
        if not isinstance(route, APIRoute):
            continue
        dep_calls = [d.call for d in route.dependant.dependencies]
        assert require_admin in dep_calls, (
            f"Admin route {route.path} is missing require_admin"
        )

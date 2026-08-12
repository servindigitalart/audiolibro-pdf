"""
Unit Tests: Admin Dashboard Service (Phase 4A)
===============================================
Tests for:
  - DashboardService.get_kpis()  — user counts, MRR, costs, content, conversion
  - DashboardService.get_growth() — daily signup time series
  - DashboardService.get_activity() — activity feed formatting
  - Admin route dependency enforcement
  - Zero-state (empty DB) handling
  - MRR calculation from plan distribution
  - Gross margin calculation
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4
from datetime import datetime

from app.analytics.dashboard_service import DashboardService, _activity_severity, _strip_props

pytestmark = pytest.mark.unit


# ── _strip_props helper ────────────────────────────────────────────────────────

def test_strip_props_removes_sensitive_keys():
    props = {"plan": "PRO", "password": "s3cr3t", "token": "abc", "trigger": "quota"}
    cleaned = _strip_props(props)
    assert "password" not in cleaned
    assert "token"    not in cleaned
    assert cleaned["plan"]    == "PRO"
    assert cleaned["trigger"] == "quota"


def test_strip_props_none_returns_empty():
    assert _strip_props(None) == {}


def test_strip_props_case_insensitive():
    props = {"PASSWORD": "x", "plan": "FREE"}
    cleaned = _strip_props(props)
    assert "PASSWORD" not in cleaned
    assert cleaned["plan"] == "FREE"


# ── _activity_severity ─────────────────────────────────────────────────────────

def test_severity_warning_for_quota_exceeded():
    assert _activity_severity("quota_exceeded") == "warning"


def test_severity_success_for_completed():
    assert _activity_severity("audiobook_completed") == "success"
    assert _activity_severity("upgrade_clicked")     == "success"


def test_severity_info_for_paywall():
    assert _activity_severity("paywall_viewed") == "info"


def test_severity_neutral_for_unknown():
    assert _activity_severity("player_opened") == "neutral"


# ── DashboardService.get_kpis ─────────────────────────────────────────────────

def _make_scalar_sequence(*values):
    """
    Return an AsyncMock whose scalar() calls return values in order.
    """
    call_count = 0
    results = list(values)

    async def mock_scalar(stmt):
        nonlocal call_count
        val = results[call_count] if call_count < len(results) else 0
        call_count += 1
        return val

    db = AsyncMock()
    db.scalar = mock_scalar
    return db


async def test_get_kpis_calculates_mrr_from_plan_distribution():
    # Simulate:  100 FREE @ $0, 20 BASIC @ $9, 10 PRO @ $29 → MRR = $470
    call_count = 0

    plan_rows = [("FREE", 100), ("BASIC", 20), ("PRO", 10)]
    mock_plan_result = MagicMock()
    mock_plan_result.all.return_value = plan_rows

    ls_row = MagicMock()
    ls_row.__getitem__ = lambda _, i: [None, None, None][i]
    mock_ls_result = MagicMock()
    mock_ls_result.one.return_value = ls_row

    scalar_values = [
        130,   # total users
        5,     # active 7d
        20,    # active 30d
        # plan_rows via execute() → not scalar
        # monthly_cost via CostTracker → execute(), not scalar
        50,    # audiobooks_generated
        # ls stats via execute() → not scalar
        0,     # quota_exceeded
        10,    # paywall_views
        2,     # upgrades
    ]
    scalar_call = 0

    async def mock_scalar(stmt):
        nonlocal scalar_call
        v = scalar_values[scalar_call] if scalar_call < len(scalar_values) else 0
        scalar_call += 1
        return v

    execute_call = 0

    async def mock_execute(stmt):
        nonlocal execute_call
        execute_call += 1
        if execute_call == 1:    # plan distribution
            return mock_plan_result
        return mock_ls_result    # listening stats

    db = AsyncMock()
    db.scalar  = mock_scalar
    db.execute = mock_execute

    result = await DashboardService.get_kpis(db)

    assert result["users"]["total"]  == 130
    assert result["users"]["free"]   == 100
    assert result["users"]["paid"]   == 30

    # MRR: 20×9 + 10×29 = 180 + 290 = 470
    assert result["revenue"]["mrr_usd"] == 470.0
    # ARR projection
    assert result["revenue"]["arr_projected_usd"] == pytest.approx(470.0 * 12)

    assert result["content"]["audiobooks_generated"] == 50
    assert result["conversion"]["paywall_views_30d"] == 10
    assert result["conversion"]["upgrade_clicks_30d"] == 2
    assert result["conversion"]["upgrade_conversion_rate_pct"] == pytest.approx(20.0)


async def test_get_kpis_zero_state():
    """All counts zero — should not divide by zero."""
    mock_plan_result = MagicMock()
    mock_plan_result.all.return_value = []

    ls_row = MagicMock()
    ls_row.__getitem__ = lambda _, i: None

    mock_ls_result = MagicMock()
    mock_ls_result.one.return_value = ls_row

    execute_call = 0

    async def mock_execute(stmt):
        nonlocal execute_call
        execute_call += 1
        if execute_call == 1:
            return mock_plan_result
        return mock_ls_result

    db = AsyncMock()
    db.scalar  = AsyncMock(return_value=0)
    db.execute = mock_execute

    result = await DashboardService.get_kpis(db)

    assert result["users"]["total"]  == 0
    assert result["revenue"]["mrr_usd"] == 0.0
    assert result["revenue"]["arpu_usd"] == 0.0
    assert result["revenue"]["arppu_usd"] == 0.0
    assert result["costs"]["estimated_gross_margin_pct"] == 0.0
    assert result["conversion"]["upgrade_conversion_rate_pct"] == 0.0


async def test_get_kpis_gross_margin_calculation():
    """Verify: (MRR - costs) / MRR × 100."""
    mock_plan_result = MagicMock()
    mock_plan_result.all.return_value = [("PRO", 10)]  # 10 × $29 = $290 MRR

    ls_row = MagicMock()
    ls_row.__getitem__ = lambda _, i: None
    mock_ls_result = MagicMock()
    mock_ls_result.one.return_value = ls_row

    scalar_values = [10, 5, 8, 5, 0, 0, 0]
    scalar_call = 0

    async def mock_scalar(stmt):
        nonlocal scalar_call
        v = scalar_values[scalar_call] if scalar_call < len(scalar_values) else 0
        scalar_call += 1
        return v

    execute_call = 0

    async def mock_execute(stmt):
        nonlocal execute_call
        execute_call += 1
        if execute_call == 1:
            return mock_plan_result
        return mock_ls_result

    db = AsyncMock()
    db.scalar  = mock_scalar
    db.execute = mock_execute

    # Spend comes from the cost ledger, not from job estimates.
    with patch(
        "app.analytics.dashboard_service.CostTracker.get_system_cost_trend",
        new_callable=AsyncMock,
        return_value=[{"date": "2026-08-01", "cost": 29.0}],
    ):
        result = await DashboardService.get_kpis(db)

    mrr   = 290.0
    costs = 29.0
    expected_margin = (mrr - costs) / mrr * 100  # ~90%

    assert result["revenue"]["mrr_usd"] == mrr
    assert result["costs"]["monthly_estimated_usd"] == pytest.approx(29.0)
    assert result["costs"]["estimated_gross_margin_pct"] == pytest.approx(expected_margin, abs=0.1)


async def test_get_kpis_arpu_arppu_computed():
    """ARPU = MRR / total_users; ARPPU = MRR / paid_users."""
    mock_plan_result = MagicMock()
    # 80 FREE, 20 PRO ($29) → MRR = 580, paid = 20, total = 100
    mock_plan_result.all.return_value = [("FREE", 80), ("PRO", 20)]

    ls_row = MagicMock()
    ls_row.__getitem__ = lambda _, i: None
    mock_ls_result = MagicMock()
    mock_ls_result.one.return_value = ls_row

    scalar_values = [100, 10, 30, 0, 5, 0, 0, 0]
    scalar_call = 0

    async def mock_scalar(stmt):
        nonlocal scalar_call
        v = scalar_values[scalar_call] if scalar_call < len(scalar_values) else 0
        scalar_call += 1
        return v

    execute_call = 0

    async def mock_execute(stmt):
        nonlocal execute_call
        execute_call += 1
        if execute_call == 1:
            return mock_plan_result
        return mock_ls_result

    db = AsyncMock()
    db.scalar  = mock_scalar
    db.execute = mock_execute

    result = await DashboardService.get_kpis(db)

    assert result["revenue"]["mrr_usd"] == 580.0
    assert result["revenue"]["arpu_usd"]  == pytest.approx(5.8, abs=0.01)
    assert result["revenue"]["arppu_usd"] == pytest.approx(29.0, abs=0.01)


# ── DashboardService.get_growth ───────────────────────────────────────────────

async def test_get_growth_returns_time_series():
    from datetime import date

    row1 = MagicMock()
    row1.day     = date(2026, 5, 1)
    row1.signups = 3

    row2 = MagicMock()
    row2.day     = date(2026, 5, 2)
    row2.signups = 7

    mock_result = MagicMock()
    mock_result.all.return_value = [row1, row2]

    db = AsyncMock()
    db.execute = AsyncMock(return_value=mock_result)

    result = await DashboardService.get_growth(db, days=30)

    assert result["period_days"] == 30
    assert len(result["data"]) == 2
    assert result["data"][0]["signups"] == 3
    assert result["data"][1]["signups"] == 7


async def test_get_growth_empty():
    mock_result = MagicMock()
    mock_result.all.return_value = []

    db = AsyncMock()
    db.execute = AsyncMock(return_value=mock_result)

    result = await DashboardService.get_growth(db, days=7)

    assert result["period_days"] == 7
    assert result["data"] == []


# ── DashboardService.get_activity ─────────────────────────────────────────────

async def test_get_activity_formats_events():
    row = MagicMock()
    row.event_type = "upgrade_clicked"
    row.created_at = datetime(2026, 5, 28, 10, 0, 0)
    row.user_id    = uuid4()
    row.properties = {"plan": "PRO"}

    mock_result = MagicMock()
    mock_result.all.return_value = [row]

    db = AsyncMock()
    db.execute = AsyncMock(return_value=mock_result)

    result = await DashboardService.get_activity(db, limit=10)

    assert result["total"] == 1
    event = result["events"][0]
    assert event["event_type"] == "upgrade_clicked"
    assert event["label"]      == "Upgrade CTA clicked"
    assert event["severity"]   == "success"
    assert len(event["user_id_prefix"]) == 8
    assert event["properties"]["plan"] == "PRO"


async def test_get_activity_anon_user():
    row = MagicMock()
    row.event_type = "paywall_viewed"
    row.created_at = datetime(2026, 5, 28, 12, 0, 0)
    row.user_id    = None
    row.properties = {}

    mock_result = MagicMock()
    mock_result.all.return_value = [row]

    db = AsyncMock()
    db.execute = AsyncMock(return_value=mock_result)

    result = await DashboardService.get_activity(db, limit=50)

    assert result["events"][0]["user_id_prefix"] == "anon"


async def test_get_activity_strips_sensitive_props():
    row = MagicMock()
    row.event_type = "player_opened"
    row.created_at = datetime(2026, 5, 28, 9, 0, 0)
    row.user_id    = uuid4()
    row.properties = {"plan": "FREE", "token": "secret_value"}

    mock_result = MagicMock()
    mock_result.all.return_value = [row]

    db = AsyncMock()
    db.execute = AsyncMock(return_value=mock_result)

    result = await DashboardService.get_activity(db, limit=50)

    props = result["events"][0]["properties"]
    assert "token" not in props
    assert props["plan"] == "FREE"


async def test_get_activity_empty():
    mock_result = MagicMock()
    mock_result.all.return_value = []

    db = AsyncMock()
    db.execute = AsyncMock(return_value=mock_result)

    result = await DashboardService.get_activity(db, limit=50)

    assert result["total"]  == 0
    assert result["events"] == []


# ── Admin route dependency enforcement ────────────────────────────────────────

def test_admin_dashboard_router_uses_require_admin():
    """Verify all routes declare require_admin as a dependency (function-param style)."""
    from app.routers.admin_dashboard import router
    from app.core.auth_dependencies import require_admin
    from fastapi.routing import APIRoute

    for route in router.routes:
        if not isinstance(route, APIRoute):
            continue
        dep_calls = [d.call for d in route.dependant.dependencies]
        assert require_admin in dep_calls, (
            f"Route {route.path} is missing require_admin dependency"
        )

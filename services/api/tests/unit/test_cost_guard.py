"""
Unit Tests: Cost Protection (Phase 0C)
======================================
Regression coverage for the gap the audit found: RevenueProtectionService
existed with zero callers, hard_cost_limit_enabled defaulted to False, and
failed processing consumed real provider resources while appearing nowhere.

The invariants these tests protect:
  - Expensive work is refused BEFORE the first provider call, never after.
  - Quota (characters) and cost (money) are separate gates.
  - A retried chunk is charged once, however many attempts it took.
  - A failed attempt stays countable without inventing a charge.
"""
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.financial.cost.cost_guard import CostProtectionError, check_processing_allowed
from app.pricing.protection import CostCapExceeded, RevenueProtectionService
from app.pricing.tiers import PlanTier
from app.pricing.unit_economics import is_premium_voice, tts_cost_for_voice

pytestmark = pytest.mark.unit


# ── Helpers ───────────────────────────────────────────────────────────────────

def _spend(name, value):
    """Patch one of the three CostTracker reads the guard makes."""
    return patch(
        f"app.financial.cost.cost_guard.CostTracker.{name}",
        new_callable=AsyncMock, return_value=value,
    )


async def _run(estimated_cost, *, tier="FREE", system_mtd=0.0,
               user_daily=0.0, user_monthly=0.0, **setting_overrides):
    """Run the guard with patched spend and settings."""
    defaults = {
        "emergency_shutdown_mode": False,
        "hard_cost_limit_enabled": False,
        "global_monthly_cost_cap": 10_000.0,
        "max_job_cost_usd": 25.0,
    }
    defaults.update(setting_overrides)

    with _spend("get_system_month_to_date_cost", system_mtd), \
         _spend("get_user_daily_cost", user_daily), \
         _spend("get_user_monthly_cost", {"total_cost": user_monthly}), \
         patch.multiple("app.financial.cost.cost_guard.settings", **defaults):
        return await check_processing_allowed(
            db=AsyncMock(),          # the guard only reads through CostTracker
            user_id=uuid4(),
            plan_tier=tier,
            estimated_job_cost_usd=estimated_cost,
            redis=None,
        )


# ── 1. Under the limit → allowed ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_job_under_cost_limit_is_allowed():
    assert await _run(8.64) is None  # a 540k-char Neural2 book, worst realistic case


@pytest.mark.asyncio
async def test_normal_free_tier_book_is_allowed_with_caps_disabled():
    """
    The regression that matters most: FREE's daily cap is $0.09 while a full
    50k-char quota job costs $0.80.  Wiring protection must NOT reject it.
    """
    assert await _run(0.80, tier="FREE", user_daily=0.0) is None


# ── 2. Over the per-job ceiling → rejected before TTS ─────────────────────────

@pytest.mark.asyncio
async def test_job_over_cost_limit_is_rejected():
    with pytest.raises(CostProtectionError) as exc:
        await _run(30.0, max_job_cost_usd=25.0)
    assert exc.value.reason == "job_cost_ceiling"
    assert "$30.00" in exc.value.user_message


@pytest.mark.asyncio
async def test_job_ceiling_applies_regardless_of_feature_flag():
    """The per-job ceiling is always on — it is not gated by hard_cost_limit_enabled."""
    with pytest.raises(CostProtectionError):
        await _run(999.0, hard_cost_limit_enabled=False)


# ── 3. User over accumulated limit → rejected ─────────────────────────────────

@pytest.mark.asyncio
async def test_user_over_daily_cap_is_rejected_when_enabled():
    with pytest.raises(CostProtectionError) as exc:
        await _run(0.10, tier="FREE", user_daily=0.50, hard_cost_limit_enabled=True)
    assert exc.value.reason == "user_daily_cap"


@pytest.mark.asyncio
async def test_user_over_monthly_cap_is_rejected_when_enabled():
    with pytest.raises(CostProtectionError) as exc:
        await _run(0.10, tier="FREE", user_daily=0.0, user_monthly=5.0,
                   hard_cost_limit_enabled=True)
    assert exc.value.reason == "user_monthly_cap"


@pytest.mark.asyncio
async def test_user_caps_are_not_enforced_when_flag_is_off():
    """Documents the deliberate default: tier caps stay off until recalibrated."""
    assert await _run(0.10, tier="FREE", user_daily=99.0,
                      hard_cost_limit_enabled=False) is None


# ── 4. Global hard limit → rejected ───────────────────────────────────────────

@pytest.mark.asyncio
async def test_global_monthly_cap_rejects():
    with pytest.raises(CostProtectionError) as exc:
        await _run(5.0, system_mtd=9_998.0, global_monthly_cost_cap=10_000.0)
    assert exc.value.reason == "global_monthly_cap"


@pytest.mark.asyncio
async def test_emergency_shutdown_rejects_everything():
    with pytest.raises(CostProtectionError) as exc:
        await _run(0.01, emergency_shutdown_mode=True)
    assert exc.value.reason == "emergency_shutdown"


@pytest.mark.asyncio
async def test_emergency_shutdown_wins_over_every_other_check():
    """Fail-safe ordering: the kill switch is evaluated first."""
    with pytest.raises(CostProtectionError) as exc:
        await _run(0.01, emergency_shutdown_mode=True, hard_cost_limit_enabled=True,
                   user_daily=0.0, system_mtd=0.0)
    assert exc.value.reason == "emergency_shutdown"


# ── 5. Estimate is honest ─────────────────────────────────────────────────────

def test_estimate_prices_the_voice_not_the_tier():
    """A FREE user on a Neural2 voice costs the neural rate, not the standard one."""
    assert tts_cost_for_voice(1_000_000, "en-US-Neural2-A") == pytest.approx(16.0)
    assert tts_cost_for_voice(1_000_000, "en-US-Standard-B") == pytest.approx(4.0)


def test_unknown_voice_assumes_the_expensive_rate():
    """Over-estimating spend is the safe direction for a guard that gates money."""
    assert is_premium_voice(None) is True
    assert tts_cost_for_voice(1_000_000, None) == pytest.approx(16.0)


def test_estimate_excludes_monthly_infra_overhead():
    """
    user_cost() folds in $0.15/month of per-user overhead.  Charging that to a
    single job made a 1k-char job look like $0.15 against a real $0.016.
    """
    assert tts_cost_for_voice(1_000, "en-US-Neural2-A") == pytest.approx(0.016)


def test_zero_characters_costs_nothing():
    assert tts_cost_for_voice(0, "en-US-Neural2-A") == 0.0


# ── 6. Job ceiling is a pure check on the existing service ────────────────────

def test_check_job_estimate_allows_under_cap():
    assert RevenueProtectionService.check_job_estimate("u1", 10.0, 25.0) is None


def test_check_job_estimate_raises_over_cap():
    with pytest.raises(CostCapExceeded) as exc:
        RevenueProtectionService.check_job_estimate("u1", 26.0, 25.0)
    assert exc.value.cap_type == "job"


def test_check_job_estimate_disabled_by_zero_cap():
    assert RevenueProtectionService.check_job_estimate("u1", 1e9, 0.0) is None


# ── 7. Rejection is terminal and costs nothing ────────────────────────────────

@pytest.mark.asyncio
async def test_rejected_job_is_marked_failed_without_retry():
    """
    A refused job must not propagate to Celery: nothing was spent, and
    retrying would only pay to rediscover the same ceiling.
    """
    from app.tasks.processing import _dispatch_job

    with patch(
        "app.tasks.processing._process_job_async", new_callable=AsyncMock,
        side_effect=CostProtectionError("job_cost_ceiling", "This document is too large."),
    ):
        with patch(
            "app.tasks.processing._mark_job_failed", new_callable=AsyncMock
        ) as mock_fail:
            await _dispatch_job(uuid4(), "task-1", 0)  # must not raise

    mock_fail.assert_awaited_once()
    # The user sees the actionable message, not the internal reason code.
    assert mock_fail.call_args[0][1] == "This document is too large."


@pytest.mark.asyncio
async def test_rejected_job_does_not_consume_quota():
    """
    Quota is charged only on successful completion.  A cost rejection happens
    before synthesis, so the user must lose no characters over it.
    """
    from app.tasks.processing import _dispatch_job

    with patch(
        "app.tasks.processing._process_job_async", new_callable=AsyncMock,
        side_effect=CostProtectionError("emergency_shutdown", "Paused."),
    ):
        with patch("app.tasks.processing._mark_job_failed", new_callable=AsyncMock):
            with patch(
                "app.financial.quota.quota_service.QuotaService.increment_usage",
                new_callable=AsyncMock,
            ) as mock_quota:
                await _dispatch_job(uuid4(), "task-2", 0)

    mock_quota.assert_not_awaited()


# ── 8. Protection cannot be bypassed by an alternate path ─────────────────────
# The worker has two TTS call sites (the no-chapters fallback and the per-chapter
# loop).  These read the source so a third path added later cannot quietly skip
# the guard or drop cost attribution.

def _worker_source() -> str:
    from pathlib import Path
    import app.tasks.processing as proc
    return Path(proc.__file__).read_text()


def test_guard_runs_before_any_tts_call():
    src = _worker_source()
    guard_at = src.index("await check_processing_allowed(")
    first_tts_at = src.index("tts_service.synthesize_text(")
    assert guard_at < first_tts_at, (
        "check_processing_allowed must run before the first paid provider call"
    )


def test_estimate_is_persisted_before_the_guard_runs():
    src = _worker_source()
    assert src.index("job.estimated_cost_usd =") < src.index("await check_processing_allowed("), (
        "the job estimate must be persisted before protection can reject the job"
    )


def test_every_tts_call_site_carries_cost_attribution():
    """Both synthesis paths must attribute spend to a document and a job."""
    src = _worker_source()
    call_count = src.count("tts_service.synthesize_text(")
    assert call_count == 2, f"expected 2 TTS call sites, found {call_count}"

    # Each call site's argument block must pass both ids.
    for chunk in src.split("tts_service.synthesize_text(")[1:]:
        args = chunk[: chunk.index(")")]
        assert "document_id=" in args and "job_id=" in args, (
            "a TTS call site is missing cost attribution"
        )


def test_worker_has_no_second_cost_protection_system():
    """Phase 0C wires the existing service; it must not grow a rival."""
    src = _worker_source()
    assert src.count("await check_processing_allowed(") == 1

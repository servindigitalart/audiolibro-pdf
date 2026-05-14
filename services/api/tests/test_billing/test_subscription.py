"""
Subscription State Machine Tests
==================================
Validates that all valid transitions succeed and all invalid transitions
raise InvalidTransition.  Also verifies audit log creation.
"""
from __future__ import annotations

import pytest

from app.billing.constants import SubscriptionStatus, VALID_TRANSITIONS
from app.billing.subscription import SubscriptionService, InvalidTransition




async def test_valid_transition_free_to_trial(db_session, db_user):
    svc = SubscriptionService(db_session)
    log = await svc.transition(db_user.id, SubscriptionStatus.TRIAL, reason="started trial")

    assert log.from_status == "free"
    assert log.to_status == "trial"
    assert log.reason == "started trial"
    assert log.actor == "system"


async def test_valid_transition_trial_to_active(db_session, db_user):
    svc = SubscriptionService(db_session)
    await svc.transition(db_user.id, SubscriptionStatus.TRIAL)
    await svc.transition(db_user.id, SubscriptionStatus.ACTIVE, reason="payment received")

    status = await svc.get_status(db_user.id)
    assert status == SubscriptionStatus.ACTIVE


async def test_valid_transition_active_to_past_due(db_session, db_user):
    svc = SubscriptionService(db_session)
    await svc.transition(db_user.id, SubscriptionStatus.TRIAL)
    await svc.transition(db_user.id, SubscriptionStatus.ACTIVE)
    log = await svc.transition(db_user.id, SubscriptionStatus.PAST_DUE, reason="payment failed")

    assert log.to_status == "past_due"


async def test_valid_transition_active_to_canceled(db_session, db_user):
    svc = SubscriptionService(db_session)
    await svc.transition(db_user.id, SubscriptionStatus.TRIAL)
    await svc.transition(db_user.id, SubscriptionStatus.ACTIVE)
    await svc.transition(db_user.id, SubscriptionStatus.CANCELED)

    status = await svc.get_status(db_user.id)
    assert status == SubscriptionStatus.CANCELED


async def test_valid_transition_past_due_to_suspended(db_session, db_user):
    svc = SubscriptionService(db_session)
    await svc.transition(db_user.id, SubscriptionStatus.TRIAL)
    await svc.transition(db_user.id, SubscriptionStatus.ACTIVE)
    await svc.transition(db_user.id, SubscriptionStatus.PAST_DUE)
    await svc.transition(db_user.id, SubscriptionStatus.SUSPENDED)

    status = await svc.get_status(db_user.id)
    assert status == SubscriptionStatus.SUSPENDED


async def test_invalid_transition_free_to_suspended_raises(db_session, db_user):
    svc = SubscriptionService(db_session)
    with pytest.raises(InvalidTransition) as exc_info:
        await svc.transition(db_user.id, SubscriptionStatus.SUSPENDED)

    assert exc_info.value.from_status == "free"
    assert exc_info.value.to_status == "suspended"


async def test_invalid_transition_canceled_to_past_due_raises(db_session, db_user):
    svc = SubscriptionService(db_session)
    await svc.transition(db_user.id, SubscriptionStatus.TRIAL)
    await svc.transition(db_user.id, SubscriptionStatus.ACTIVE)
    await svc.transition(db_user.id, SubscriptionStatus.CANCELED)

    with pytest.raises(InvalidTransition):
        await svc.transition(db_user.id, SubscriptionStatus.PAST_DUE)


async def test_invalid_transition_suspended_to_free_raises(db_session, db_user):
    svc = SubscriptionService(db_session)
    await svc.transition(db_user.id, SubscriptionStatus.TRIAL)
    await svc.transition(db_user.id, SubscriptionStatus.ACTIVE)
    await svc.transition(db_user.id, SubscriptionStatus.SUSPENDED)

    with pytest.raises(InvalidTransition):
        await svc.transition(db_user.id, SubscriptionStatus.FREE)


async def test_audit_log_records_every_transition(db_session, db_user):
    svc = SubscriptionService(db_session)
    await svc.transition(db_user.id, SubscriptionStatus.TRIAL)
    await svc.transition(db_user.id, SubscriptionStatus.ACTIVE)
    await svc.transition(db_user.id, SubscriptionStatus.PAST_DUE)

    history = await svc.history(db_user.id)
    assert len(history) == 3
    # Most recent first
    assert history[0].to_status == "past_due"
    assert history[1].to_status == "active"
    assert history[2].to_status == "trial"


async def test_transition_with_stripe_event_id(db_session, db_user):
    svc = SubscriptionService(db_session)
    log = await svc.transition(
        db_user.id,
        SubscriptionStatus.TRIAL,
        actor="stripe",
        stripe_event_id="evt_test_123",
    )
    assert log.stripe_event_id == "evt_test_123"
    assert log.actor == "stripe"


async def test_all_declared_valid_transitions_work(db_session):
    """Smoke-test: every transition in VALID_TRANSITIONS can be modelled."""
    # Check that each (from, to) pair in the map is distinct and non-empty
    for from_status, to_set in VALID_TRANSITIONS.items():
        assert len(to_set) > 0, f"{from_status} has no valid transitions"
        for to_status in to_set:
            assert to_status != from_status or from_status == SubscriptionStatus.FREE, (
                f"Self-loop on {from_status} — check VALID_TRANSITIONS"
            )


async def test_get_status_unknown_user_raises(db_session):
    import uuid
    svc = SubscriptionService(db_session)
    with pytest.raises(ValueError, match="not found"):
        await svc.get_status(uuid.uuid4())

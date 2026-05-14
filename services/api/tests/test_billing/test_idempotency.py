"""
Idempotency Service Tests
==========================
Validates two-phase locking, duplicate detection, concurrent request handling,
and response caching.
"""
from __future__ import annotations

import uuid

import pytest

from app.billing.idempotency import IdempotencyService, DuplicateRequest, ConcurrentRequest




async def test_lock_creates_locked_row(db_session, db_user):
    svc = IdempotencyService(db_session)
    key = f"test_lock_{uuid.uuid4().hex}"

    await svc.lock(key, db_user.id)

    from app.billing.models import IdempotencyKey
    from sqlalchemy import select
    result = await db_session.execute(
        select(IdempotencyKey).where(IdempotencyKey.idempotency_key == key)
    )
    row = result.scalar_one_or_none()
    assert row is not None
    assert row.status == "locked"


async def test_complete_marks_row_complete(db_session, db_user):
    svc = IdempotencyService(db_session)
    key = f"test_complete_{uuid.uuid4().hex}"

    await svc.lock(key, db_user.id)
    await svc.complete(key, {"result": "ok"}, status_code=201)

    from app.billing.models import IdempotencyKey
    from sqlalchemy import select
    result = await db_session.execute(
        select(IdempotencyKey).where(IdempotencyKey.idempotency_key == key)
    )
    row = result.scalar_one_or_none()
    assert row.status == "complete"
    assert row.response_status_code == 201
    assert '"result": "ok"' in row.response_payload


async def test_second_lock_on_complete_raises_duplicate_request(db_session, db_user):
    svc = IdempotencyService(db_session)
    key = f"test_dup_{uuid.uuid4().hex}"

    await svc.lock(key, db_user.id)
    await svc.complete(key, {"charge_id": "ch_123"}, status_code=200)

    with pytest.raises(DuplicateRequest) as exc_info:
        await svc.lock(key, db_user.id)

    assert exc_info.value.key == key
    assert "ch_123" in exc_info.value.response_payload
    assert exc_info.value.status_code == 200


async def test_second_lock_on_locked_raises_concurrent_request(db_session, db_user):
    svc = IdempotencyService(db_session)
    key = f"test_concurrent_{uuid.uuid4().hex}"

    await svc.lock(key, db_user.id)

    with pytest.raises(ConcurrentRequest) as exc_info:
        await svc.lock(key, db_user.id)

    assert exc_info.value.key == key


async def test_different_keys_are_independent(db_session, db_user):
    svc = IdempotencyService(db_session)
    key_a = f"key_a_{uuid.uuid4().hex}"
    key_b = f"key_b_{uuid.uuid4().hex}"

    await svc.lock(key_a, db_user.id)
    await svc.lock(key_b, db_user.id)  # must not raise

    await svc.complete(key_a, {}, 200)
    await svc.complete(key_b, {}, 200)


async def test_hash_request_is_deterministic():
    body = b'{"amount": 100, "currency": "usd"}'
    h1 = IdempotencyService.hash_request(body)
    h2 = IdempotencyService.hash_request(body)
    assert h1 == h2
    assert len(h1) == 64  # SHA-256 hex


async def test_hash_request_different_bodies_differ():
    h1 = IdempotencyService.hash_request(b'{"amount": 100}')
    h2 = IdempotencyService.hash_request(b'{"amount": 200}')
    assert h1 != h2


async def test_lock_without_user_id_succeeds(db_session):
    """user_id=None → no FK constraint → must succeed."""
    svc = IdempotencyService(db_session)
    key = f"anon_{uuid.uuid4().hex}"
    await svc.lock(key, user_id=None)  # must not raise

    from app.billing.models import IdempotencyKey
    from sqlalchemy import select
    result = await db_session.execute(
        select(IdempotencyKey).where(IdempotencyKey.idempotency_key == key)
    )
    row = result.scalar_one_or_none()
    assert row is not None
    assert row.user_id is None


async def test_complete_with_string_payload(db_session, db_user):
    svc = IdempotencyService(db_session)
    key = f"str_payload_{uuid.uuid4().hex}"

    await svc.lock(key, db_user.id)
    await svc.complete(key, '{"already": "serialized"}', 200)

    from app.billing.models import IdempotencyKey
    from sqlalchemy import select
    result = await db_session.execute(
        select(IdempotencyKey).where(IdempotencyKey.idempotency_key == key)
    )
    row = result.scalar_one_or_none()
    assert row.response_payload == '{"already": "serialized"}'

"""
Billing Engine — Idempotency Service
=======================================
Two-phase locking protocol:

  Phase 1 — LOCK:
    INSERT idempotency_key with status='locked'.
    If the row already exists and status='complete', return cached response.
    If the row already exists and status='locked', raise ConcurrentRequest.

  Phase 2 — COMPLETE:
    UPDATE row to status='complete' with the serialised response payload.

Callers must call lock() before the operation and complete() after success.
On failure the row is left in 'locked' status — it will expire and can be retried.

TTL is enforced by an expires_at column; a periodic cleanup job (or Postgres
partitioning) removes expired rows.
"""
from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.billing.constants import IDEMPOTENCY_TTL_SECONDS
from app.billing.models import IdempotencyKey


class DuplicateRequest(Exception):
    """Raised when an idempotency key is found with status='complete'."""

    def __init__(self, key: str, response_payload: str, status_code: int) -> None:
        super().__init__(f"Duplicate request for idempotency key {key!r}")
        self.key = key
        self.response_payload = response_payload
        self.status_code = status_code


class ConcurrentRequest(Exception):
    """Raised when an idempotency key is found with status='locked' (in-flight)."""

    def __init__(self, key: str) -> None:
        super().__init__(f"Concurrent in-flight request for idempotency key {key!r}")
        self.key = key


class IdempotencyService:
    """
    Prevents duplicate billing operations via DB-persisted two-phase locking.

    Example usage in a billing endpoint:
        try:
            await svc.lock(idempotency_key, user_id, request_hash)
        except DuplicateRequest as dr:
            return JSONResponse(json.loads(dr.response_payload), status_code=dr.status_code)
        except ConcurrentRequest:
            raise HTTPException(409, "Request in progress — retry later")

        # ... perform the billing operation ...

        await svc.complete(idempotency_key, response_payload, 200)
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ── Phase 1 ───────────────────────────────────────────────────────────────

    async def lock(
        self,
        key: str,
        user_id: Optional[uuid.UUID] = None,
        request_hash: Optional[str] = None,
    ) -> None:
        """
        Attempt to claim the idempotency key.

        Raises:
          DuplicateRequest   — key exists and is complete → return cached response
          ConcurrentRequest  — key exists and is locked   → client should retry
        """
        existing = await self._get(key)

        if existing is not None:
            if existing.status == "complete":
                raise DuplicateRequest(
                    key,
                    existing.response_payload or "{}",
                    existing.response_status_code or 200,
                )
            raise ConcurrentRequest(key)

        expires_at = datetime.now(timezone.utc) + timedelta(seconds=IDEMPOTENCY_TTL_SECONDS)
        row = IdempotencyKey(
            idempotency_key=key,
            user_id=user_id,
            status="locked",
            request_hash=request_hash,
            expires_at=expires_at,
        )
        self._session.add(row)
        try:
            await self._session.commit()
        except IntegrityError:
            await self._session.rollback()
            # Race condition: another request inserted between our SELECT and INSERT
            existing = await self._get(key)
            if existing and existing.status == "complete":
                raise DuplicateRequest(
                    key,
                    existing.response_payload or "{}",
                    existing.response_status_code or 200,
                )
            raise ConcurrentRequest(key)

    # ── Phase 2 ───────────────────────────────────────────────────────────────

    async def complete(
        self,
        key: str,
        response_payload: Any,
        status_code: int = 200,
    ) -> None:
        """Mark the idempotency key as complete with the serialised response."""
        payload_str = json.dumps(response_payload) if not isinstance(response_payload, str) else response_payload
        await self._session.execute(
            update(IdempotencyKey)
            .where(IdempotencyKey.idempotency_key == key)
            .values(
                status="complete",
                response_payload=payload_str,
                response_status_code=status_code,
                completed_at=datetime.now(timezone.utc),
            )
        )
        await self._session.commit()

    # ── Helpers ───────────────────────────────────────────────────────────────

    async def _get(self, key: str) -> Optional[IdempotencyKey]:
        result = await self._session.execute(
            select(IdempotencyKey).where(IdempotencyKey.idempotency_key == key)
        )
        return result.scalar_one_or_none()

    @staticmethod
    def hash_request(body: bytes) -> str:
        return hashlib.sha256(body).hexdigest()

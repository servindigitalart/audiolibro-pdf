"""
Unit Tests: app.services.auth_service
======================================
Tests for AuthService business logic.

Strategy
--------
- DB is replaced with a lightweight AsyncMock so tests run without PostgreSQL.
- Redis is replaced by the _FakeRedis injected by the autouse mock_redis fixture
  (conftest.py).  Tests that inspect Redis state receive mock_redis as a param.
- No FastAPI client is created; methods are called directly.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password, create_refresh_token
from app.db.models.user import User
from app.services.auth_service import AuthService

pytestmark = pytest.mark.unit


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_db(found_user: User | None = None) -> AsyncMock:
    """Return an AsyncSession mock whose execute() yields found_user."""
    db = AsyncMock(spec=AsyncSession)
    result = MagicMock()
    result.scalar_one_or_none.return_value = found_user
    db.execute.return_value = result
    return db


def _active_user(email: str = "u@example.com", password: str = "Test12345!") -> User:
    return User(
        id=uuid4(),
        email=email,
        hashed_password=hash_password(password),
        is_active=True,
        is_verified=False,
        role="user",
    )


# ── register_user ─────────────────────────────────────────────────────────────

class TestRegisterUser:
    async def test_success_creates_and_returns_user(self):
        db = _make_db(found_user=None)

        user = await AuthService.register_user("new@example.com", "Test12345!", db)

        assert user.email == "new@example.com"
        assert user.is_active is True
        assert user.role == "user"
        db.add.assert_called_once_with(user)
        db.commit.assert_awaited_once()
        db.refresh.assert_awaited_once_with(user)

    async def test_duplicate_email_raises_400(self):
        existing = _active_user(email="dup@example.com")
        db = _make_db(found_user=existing)

        with pytest.raises(HTTPException) as exc_info:
            await AuthService.register_user("dup@example.com", "Test12345!", db)

        assert exc_info.value.status_code == 400
        db.add.assert_not_called()

    async def test_password_is_hashed(self):
        db = _make_db(found_user=None)
        user = await AuthService.register_user("x@example.com", "Test12345!", db)
        assert user.hashed_password != "Test12345!"
        assert user.hashed_password.startswith("$2b$")


# ── authenticate_user ─────────────────────────────────────────────────────────

class TestAuthenticateUser:
    async def test_correct_credentials_returns_user(self):
        user = _active_user()
        db = _make_db(found_user=user)

        result = await AuthService.authenticate_user(user.email, "Test12345!", db)

        assert result is user

    async def test_wrong_password_returns_none(self):
        user = _active_user()
        db = _make_db(found_user=user)

        result = await AuthService.authenticate_user(user.email, "WrongPass9!", db)

        assert result is None

    async def test_unknown_email_returns_none(self):
        db = _make_db(found_user=None)

        result = await AuthService.authenticate_user("ghost@example.com", "Test12345!", db)

        assert result is None

    async def test_oauth_user_without_password_returns_none(self):
        oauth_user = User(
            id=uuid4(),
            email="oauth@example.com",
            hashed_password=None,   # OAuth-only: no local password
            is_active=True,
        )
        db = _make_db(found_user=oauth_user)

        result = await AuthService.authenticate_user("oauth@example.com", "Test12345!", db)

        assert result is None


# ── create_tokens ─────────────────────────────────────────────────────────────

class TestCreateTokens:
    async def test_returns_access_refresh_jti(self, mock_redis):
        user_id = uuid4()

        access, refresh, jti = await AuthService.create_tokens(user_id)

        assert access
        assert refresh
        assert jti

    async def test_jti_stored_in_redis(self, mock_redis):
        user_id = uuid4()

        _, _, jti = await AuthService.create_tokens(user_id)

        stored = mock_redis._store.get(f"refresh_token:{jti}")
        assert stored == str(user_id)

    async def test_access_and_refresh_are_different(self, mock_redis):
        user_id = uuid4()

        access, refresh, _ = await AuthService.create_tokens(user_id)

        assert access != refresh


# ── refresh_tokens ────────────────────────────────────────────────────────────

class TestRefreshTokens:
    async def test_success_returns_new_token_pair(self, mock_redis):
        user_id = uuid4()
        _, refresh_token, old_jti = await AuthService.create_tokens(user_id)

        user = User(id=user_id, email="u@example.com", is_active=True)
        db = _make_db(found_user=user)

        new_access, new_refresh = await AuthService.refresh_tokens(refresh_token, db)

        assert new_access
        assert new_refresh

    async def test_old_jti_is_invalidated(self, mock_redis):
        user_id = uuid4()
        _, refresh_token, old_jti = await AuthService.create_tokens(user_id)

        user = User(id=user_id, email="u@example.com", is_active=True)
        db = _make_db(found_user=user)

        await AuthService.refresh_tokens(refresh_token, db)

        assert f"refresh_token:{old_jti}" not in mock_redis._store

    async def test_invalid_token_raises_401(self, mock_redis):
        db = _make_db()

        with pytest.raises(HTTPException) as exc_info:
            await AuthService.refresh_tokens("not-a-token", db)

        assert exc_info.value.status_code == 401

    async def test_revoked_jti_raises_401(self, mock_redis):
        user_id = uuid4()
        _, refresh_token, jti = await AuthService.create_tokens(user_id)

        # Simulate token revocation
        del mock_redis._store[f"refresh_token:{jti}"]

        db = _make_db()

        with pytest.raises(HTTPException) as exc_info:
            await AuthService.refresh_tokens(refresh_token, db)

        assert exc_info.value.status_code == 401

    async def test_inactive_user_raises_401(self, mock_redis):
        user_id = uuid4()
        _, refresh_token, _ = await AuthService.create_tokens(user_id)

        inactive_user = User(id=user_id, email="u@example.com", is_active=False)
        db = _make_db(found_user=inactive_user)

        with pytest.raises(HTTPException) as exc_info:
            await AuthService.refresh_tokens(refresh_token, db)

        assert exc_info.value.status_code == 401


# ── logout_user ───────────────────────────────────────────────────────────────

class TestLogoutUser:
    async def test_valid_token_deletes_jti(self, mock_redis):
        user_id = uuid4()
        _, refresh_token, jti = await AuthService.create_tokens(user_id)

        await AuthService.logout_user(refresh_token)

        assert f"refresh_token:{jti}" not in mock_redis._store

    async def test_invalid_token_raises_401(self, mock_redis):
        with pytest.raises(HTTPException) as exc_info:
            await AuthService.logout_user("garbage-token")

        assert exc_info.value.status_code == 401

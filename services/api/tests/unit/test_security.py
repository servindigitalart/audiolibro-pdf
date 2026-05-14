"""
Unit Tests: app.core.security
==============================
Pure-logic tests — no DB, no Redis, no HTTP client.
All functions under test are synchronous, so no async needed here.
"""

import pytest
from uuid import uuid4

from app.core.security import (
    create_access_token,
    create_refresh_token,
    hash_password,
    verify_password,
    verify_token,
)

pytestmark = pytest.mark.unit


# ── Password hashing ──────────────────────────────────────────────────────────

def test_hash_is_not_plain_text():
    assert hash_password("Secret1!") != "Secret1!"


def test_bcrypt_salts_are_random():
    pw = "Secret1!"
    assert hash_password(pw) != hash_password(pw)


def test_verify_password_correct():
    pw = "Correct1!"
    assert verify_password(pw, hash_password(pw)) is True


def test_verify_password_wrong():
    assert verify_password("Wrong1!", hash_password("Right1!")) is False


def test_verify_password_empty_wrong():
    assert verify_password("", hash_password("Something1!")) is False


# ── Access token ──────────────────────────────────────────────────────────────

def test_access_token_payload_claims():
    uid = str(uuid4())
    token = create_access_token(subject=uid)
    payload = verify_token(token, token_type="access")

    assert payload is not None
    assert payload["sub"] == uid
    assert payload["type"] == "access"
    assert "exp" in payload
    assert "iat" in payload


def test_access_token_with_additional_claims():
    token = create_access_token(subject="abc", additional_claims={"role": "admin"})
    payload = verify_token(token, token_type="access")
    assert payload["role"] == "admin"


def test_access_token_rejected_as_refresh():
    token = create_access_token(subject=str(uuid4()))
    assert verify_token(token, token_type="refresh") is None


# ── Refresh token ─────────────────────────────────────────────────────────────

def test_refresh_token_payload_claims():
    uid = str(uuid4())
    token, jti = create_refresh_token(subject=uid)
    payload = verify_token(token, token_type="refresh")

    assert payload is not None
    assert payload["sub"] == uid
    assert payload["type"] == "refresh"
    assert payload["jti"] == jti
    assert jti  # non-empty UUID string


def test_each_refresh_token_has_unique_jti():
    uid = str(uuid4())
    _, jti1 = create_refresh_token(subject=uid)
    _, jti2 = create_refresh_token(subject=uid)
    assert jti1 != jti2


def test_refresh_token_rejected_as_access():
    token, _ = create_refresh_token(subject=str(uuid4()))
    assert verify_token(token, token_type="access") is None


# ── verify_token edge cases ───────────────────────────────────────────────────

def test_verify_token_garbage_string():
    assert verify_token("not.a.jwt.at.all", token_type="access") is None


def test_verify_token_empty_string():
    assert verify_token("", token_type="access") is None


def test_verify_token_wrong_secret(monkeypatch):
    """Token signed with a different secret must be rejected."""
    import app.core.config as cfg_mod

    # Sign a token while secret_key is patched to something different
    monkeypatch.setattr(cfg_mod.settings, "secret_key", "a-completely-different-secret-xyz")
    bad_token = create_access_token(subject="x")

    # Restore the real secret before verifying — the token must be rejected
    monkeypatch.undo()
    assert verify_token(bad_token, token_type="access") is None

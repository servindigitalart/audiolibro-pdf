"""
Integration Tests: Security Hardening
=======================================
Tests authentication bypass, token tampering, input injection,
brute-force resilience, and response integrity.

All tests run the full FastAPI request stack via AsyncClient.
"""
import base64
import json
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import uuid4

from jose import jwt as jose_jwt

from tests.factories import DEFAULT_PASSWORD, create_user
from app.core.security import create_access_token, create_refresh_token

pytestmark = pytest.mark.integration


# ── Missing / malformed auth headers ─────────────────────────────────────────

async def test_no_token_returns_401_or_403(client: AsyncClient):
    r = await client.get("/api/v1/auth/me")
    assert r.status_code in (401, 403)


async def test_empty_bearer_value_is_rejected(client: AsyncClient):
    r = await client.get("/api/v1/auth/me", headers={"Authorization": "Bearer "})
    assert r.status_code in (401, 403)


async def test_non_bearer_scheme_is_rejected(client: AsyncClient):
    r = await client.get("/api/v1/auth/me", headers={"Authorization": "Basic dXNlcjpwYXNz"})
    assert r.status_code in (401, 403)


async def test_garbage_token_is_rejected(client: AsyncClient):
    r = await client.get(
        "/api/v1/auth/me",
        headers={"Authorization": "Bearer this.is.garbage"},
    )
    assert r.status_code in (401, 403)


async def test_plain_text_token_is_rejected(client: AsyncClient):
    r = await client.get(
        "/api/v1/auth/me",
        headers={"Authorization": "Bearer notjwt"},
    )
    assert r.status_code in (401, 403)


# ── Token type confusion ──────────────────────────────────────────────────────

async def test_refresh_token_cannot_be_used_as_access_token(client: AsyncClient):
    refresh_token, _ = create_refresh_token(subject=str(uuid4()))
    r = await client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {refresh_token}"},
    )
    assert r.status_code in (401, 403)


# ── Token tampering ───────────────────────────────────────────────────────────

async def test_modified_payload_signature_mismatch_rejected(client: AsyncClient):
    """Change the 'sub' claim — signature no longer matches payload."""
    token = create_access_token(subject=str(uuid4()))
    header_b64, payload_b64, sig = token.split(".")

    padding = "=" * (4 - len(payload_b64) % 4)
    payload = json.loads(base64.urlsafe_b64decode(payload_b64 + padding))
    payload["sub"] = str(uuid4())

    tampered_payload_b64 = (
        base64.urlsafe_b64encode(json.dumps(payload).encode()).rstrip(b"=").decode()
    )
    tampered = f"{header_b64}.{tampered_payload_b64}.{sig}"

    r = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {tampered}"})
    assert r.status_code in (401, 403)


async def test_token_signed_with_wrong_secret_is_rejected(client: AsyncClient):
    forged = jose_jwt.encode(
        {"sub": str(uuid4()), "type": "access"},
        "completely-wrong-secret-key",
        algorithm="HS256",
    )
    r = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {forged}"})
    assert r.status_code in (401, 403)


async def test_token_without_type_claim_is_rejected(client: AsyncClient):
    """A JWT missing the 'type' claim should not pass verify_token."""
    import app.core.config as cfg
    token = jose_jwt.encode(
        {"sub": str(uuid4())},  # no 'type'
        cfg.settings.secret_key,
        algorithm="HS256",
    )
    r = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code in (401, 403)


# ── Input injection ───────────────────────────────────────────────────────────

async def test_sql_injection_in_email_field_returns_422(client: AsyncClient):
    r = await client.post("/api/v1/auth/register", json={
        "email": "'; DROP TABLE users; --",
        "password": DEFAULT_PASSWORD,
    })
    assert r.status_code == 422


async def test_xss_payload_in_email_field_returns_422(client: AsyncClient):
    r = await client.post("/api/v1/auth/register", json={
        "email": "<script>alert(1)</script>@xss.com",
        "password": DEFAULT_PASSWORD,
    })
    assert r.status_code == 422


async def test_oversized_email_is_rejected(client: AsyncClient):
    # local-part > 64 chars violates RFC 5321 — email-validator rejects it
    r = await client.post("/api/v1/auth/register", json={
        "email": "a" * 300 + "@example.com",
        "password": DEFAULT_PASSWORD,
    })
    assert r.status_code == 422


async def test_null_byte_in_password_handled_safely(client: AsyncClient, db_session: AsyncSession):
    await create_user(db_session, email="nullbyte@example.com")
    r = await client.post("/api/v1/auth/login", json={
        "email": "nullbyte@example.com",
        "password": "\x00malicious",
    })
    # Must not crash: 401 (wrong pw) or 422 (validation) are both acceptable
    assert r.status_code in (401, 422)
    assert r.status_code < 500


# ── Brute force resilience ────────────────────────────────────────────────────

async def test_repeated_wrong_passwords_all_return_401(
    client: AsyncClient, db_session: AsyncSession
):
    await create_user(db_session, email="brute@example.com")
    for i in range(5):
        r = await client.post("/api/v1/auth/login", json={
            "email": "brute@example.com",
            "password": f"WrongPass{i}!X",
        })
        assert r.status_code == 401, f"Attempt {i + 1} returned unexpected {r.status_code}"


async def test_nonexistent_and_existing_user_both_return_401(
    client: AsyncClient, db_session: AsyncSession
):
    """Both paths must return 401 — no timing oracle via different error codes."""
    await create_user(db_session, email="timing@example.com")

    r_existing = await client.post("/api/v1/auth/login", json={
        "email": "timing@example.com", "password": "WrongPass1!",
    })
    r_ghost = await client.post("/api/v1/auth/login", json={
        "email": "ghost999@example.com", "password": "WrongPass1!",
    })
    assert r_existing.status_code == 401
    assert r_ghost.status_code == 401


# ── Account state enforcement ─────────────────────────────────────────────────

async def test_inactive_user_login_returns_403(
    client: AsyncClient, db_session: AsyncSession
):
    await create_user(db_session, email="banned@example.com", is_active=False)
    r = await client.post("/api/v1/auth/login", json={
        "email": "banned@example.com",
        "password": DEFAULT_PASSWORD,
    })
    assert r.status_code == 403


async def test_valid_token_works_immediately_after_registration(client: AsyncClient):
    r = await client.post("/api/v1/auth/register", json={
        "email": "freshtoken@example.com",
        "password": DEFAULT_PASSWORD,
    })
    assert r.status_code == 201
    token = r.json()["access_token"]

    r2 = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert r2.status_code == 200


# ── Response integrity ────────────────────────────────────────────────────────

async def test_error_response_does_not_leak_internal_details(client: AsyncClient):
    r = await client.post("/api/v1/auth/login", json={
        "email": "nobody@example.com", "password": DEFAULT_PASSWORD,
    })
    body = r.text.lower()
    for leak in ("traceback", "sqlalchemy", "postgresql", "file \"/", "select "):
        assert leak not in body, f"Response may leak internal detail: {leak!r}"


async def test_register_response_never_includes_hashed_password(client: AsyncClient):
    r = await client.post("/api/v1/auth/register", json={
        "email": "nopw@example.com", "password": DEFAULT_PASSWORD,
    })
    assert r.status_code == 201
    body = r.json()
    assert "hashed_password" not in body
    assert "password" not in body


async def test_login_response_never_includes_hashed_password(
    client: AsyncClient, db_session: AsyncSession
):
    await create_user(db_session, email="loginpw@example.com")
    r = await client.post("/api/v1/auth/login", json={
        "email": "loginpw@example.com", "password": DEFAULT_PASSWORD,
    })
    assert r.status_code == 200
    body = r.json()
    assert "hashed_password" not in body
    assert "password" not in body


async def test_server_never_returns_500_on_auth_endpoints(client: AsyncClient):
    """Feeding garbage JSON must never produce an unhandled 500."""
    for payload in [
        {"email": None, "password": None},
        {},
        {"email": "x", "password": "y"},
    ]:
        r = await client.post("/api/v1/auth/login", json=payload)
        assert r.status_code < 500, f"Server error on payload {payload}: {r.status_code}"

"""
Integration Tests: /api/v1/auth endpoints
==========================================
Full request-response tests via AsyncClient.

Every test receives:
- client       : FastAPI test client with get_db → isolated test session
- db_session   : (when needed) direct session access for precondition setup
- mock_redis   : injected automatically (autouse); access it as a param to
                 inspect or pre-populate Redis state

Each test is wrapped in a transaction that's rolled back at teardown, so
there is zero data leakage between tests even when they share email addresses.
"""

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from tests.factories import DEFAULT_PASSWORD, create_user

pytestmark = pytest.mark.integration


# ── Register ──────────────────────────────────────────────────────────────────

async def test_register_returns_201_and_tokens(client: AsyncClient):
    r = await client.post("/api/v1/auth/register", json={
        "email": "register@example.com",
        "password": DEFAULT_PASSWORD,
    })
    assert r.status_code == 201, r.text
    body = r.json()
    assert "access_token" in body
    assert "refresh_token" in body
    assert body["token_type"] == "bearer"
    assert body["expires_in"] > 0


async def test_register_duplicate_email_returns_400(client: AsyncClient):
    payload = {"email": "dup@example.com", "password": DEFAULT_PASSWORD}
    r1 = await client.post("/api/v1/auth/register", json=payload)
    assert r1.status_code == 201

    r2 = await client.post("/api/v1/auth/register", json=payload)
    assert r2.status_code == 400


async def test_register_weak_password_returns_422(client: AsyncClient):
    r = await client.post("/api/v1/auth/register", json={
        "email": "weak@example.com",
        "password": "short",           # fails the strength validator
    })
    assert r.status_code == 422


async def test_register_invalid_email_returns_422(client: AsyncClient):
    r = await client.post("/api/v1/auth/register", json={
        "email": "not-an-email",
        "password": DEFAULT_PASSWORD,
    })
    assert r.status_code == 422


# ── Login ─────────────────────────────────────────────────────────────────────

async def test_login_correct_credentials_returns_200(
    client: AsyncClient,
    db_session: AsyncSession,
):
    await create_user(db_session, email="login@example.com")

    r = await client.post("/api/v1/auth/login", json={
        "email": "login@example.com",
        "password": DEFAULT_PASSWORD,
    })
    assert r.status_code == 200, r.text
    assert "access_token" in r.json()


async def test_login_wrong_password_returns_401(
    client: AsyncClient,
    db_session: AsyncSession,
):
    await create_user(db_session, email="badpw@example.com")

    r = await client.post("/api/v1/auth/login", json={
        "email": "badpw@example.com",
        "password": "WrongPass9!",
    })
    assert r.status_code == 401


async def test_login_unknown_email_returns_401(client: AsyncClient):
    r = await client.post("/api/v1/auth/login", json={
        "email": "ghost@example.com",
        "password": DEFAULT_PASSWORD,
    })
    assert r.status_code == 401


async def test_login_inactive_user_returns_403(
    client: AsyncClient,
    db_session: AsyncSession,
):
    await create_user(db_session, email="inactive@example.com", is_active=False)

    r = await client.post("/api/v1/auth/login", json={
        "email": "inactive@example.com",
        "password": DEFAULT_PASSWORD,
    })
    assert r.status_code == 403


# ── /me ───────────────────────────────────────────────────────────────────────

async def test_me_returns_current_user(client: AsyncClient):
    r = await client.post("/api/v1/auth/register", json={
        "email": "me@example.com",
        "password": DEFAULT_PASSWORD,
    })
    token = r.json()["access_token"]

    r2 = await client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r2.status_code == 200, r2.text
    data = r2.json()
    assert data["email"] == "me@example.com"
    assert "id" in data
    assert "created_at" in data


async def test_me_without_token_returns_403(client: AsyncClient):
    r = await client.get("/api/v1/auth/me")
    assert r.status_code in (401, 403)


async def test_me_with_invalid_token_returns_403(client: AsyncClient):
    r = await client.get(
        "/api/v1/auth/me",
        headers={"Authorization": "Bearer not-a-real-token"},
    )
    assert r.status_code in (401, 403)


# ── Full auth flow ────────────────────────────────────────────────────────────

async def test_full_register_login_me_flow(client: AsyncClient):
    email = "flow@example.com"

    # Step 1: register
    r1 = await client.post("/api/v1/auth/register", json={
        "email": email,
        "password": DEFAULT_PASSWORD,
    })
    assert r1.status_code == 201
    access_token = r1.json()["access_token"]

    # Step 2: login with same credentials
    r2 = await client.post("/api/v1/auth/login", json={
        "email": email,
        "password": DEFAULT_PASSWORD,
    })
    assert r2.status_code == 200

    # Step 3: /me with token from registration
    r3 = await client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {access_token}"},
    )
    assert r3.status_code == 200
    assert r3.json()["email"] == email

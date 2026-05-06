"""
Authentication Tests
====================
Test authentication endpoints and token management.
"""

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token, verify_token
from app.db.models.user import User


@pytest.mark.asyncio
async def test_register_success(client: AsyncClient):
    """Test successful user registration."""
    response = await client.post(
        "/api/v1/auth/register",
        json={
            "email": "newuser@example.com",
            "password": "SecurePass123",
        },
    )
    
    assert response.status_code == 201
    data = response.json()
    assert "access_token" in data
    assert "refresh_token" in data
    assert data["token_type"] == "bearer"
    assert data["expires_in"] == 15 * 60  # 15 minutes


@pytest.mark.asyncio
async def test_register_weak_password(client: AsyncClient):
    """Test registration with weak password."""
    response = await client.post(
        "/api/v1/auth/register",
        json={
            "email": "weak@example.com",
            "password": "weak",
        },
    )
    
    assert response.status_code == 422  # Validation error


@pytest.mark.asyncio
async def test_register_duplicate_email(client: AsyncClient, db_session: AsyncSession):
    """Test registration with duplicate email."""
    # First registration
    response1 = await client.post(
        "/api/v1/auth/register",
        json={
            "email": "duplicate@example.com",
            "password": "SecurePass123",
        },
    )
    assert response1.status_code == 201
    
    # Attempt duplicate registration
    response2 = await client.post(
        "/api/v1/auth/register",
        json={
            "email": "duplicate@example.com",
            "password": "SecurePass123",
        },
    )
    assert response2.status_code == 400
    assert "already registered" in response2.json()["detail"].lower()


@pytest.mark.asyncio
async def test_login_success(client: AsyncClient):
    """Test successful login."""
    # Register user first
    await client.post(
        "/api/v1/auth/register",
        json={
            "email": "login@example.com",
            "password": "SecurePass123",
        },
    )
    
    # Login
    response = await client.post(
        "/api/v1/auth/login",
        json={
            "email": "login@example.com",
            "password": "SecurePass123",
        },
    )
    
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert "refresh_token" in data


@pytest.mark.asyncio
async def test_login_wrong_password(client: AsyncClient):
    """Test login with wrong password."""
    # Register user first
    await client.post(
        "/api/v1/auth/register",
        json={
            "email": "wrongpass@example.com",
            "password": "SecurePass123",
        },
    )
    
    # Login with wrong password
    response = await client.post(
        "/api/v1/auth/login",
        json={
            "email": "wrongpass@example.com",
            "password": "WrongPassword123",
        },
    )
    
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_login_nonexistent_user(client: AsyncClient):
    """Test login with non-existent user."""
    response = await client.post(
        "/api/v1/auth/login",
        json={
            "email": "nonexistent@example.com",
            "password": "SecurePass123",
        },
    )
    
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_get_current_user(client: AsyncClient):
    """Test getting current user information."""
    # Register and get tokens
    reg_response = await client.post(
        "/api/v1/auth/register",
        json={
            "email": "currentuser@example.com",
            "password": "SecurePass123",
        },
    )
    tokens = reg_response.json()
    access_token = tokens["access_token"]
    
    # Get current user
    response = await client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {access_token}"},
    )
    
    assert response.status_code == 200
    data = response.json()
    assert data["email"] == "currentuser@example.com"
    assert data["is_active"] is True
    assert data["role"] == "user"


@pytest.mark.asyncio
async def test_get_current_user_invalid_token(client: AsyncClient):
    """Test getting current user with invalid token."""
    response = await client.get(
        "/api/v1/auth/me",
        headers={"Authorization": "Bearer invalid_token"},
    )
    
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_refresh_token(client: AsyncClient):
    """Test token refresh."""
    # Register and get tokens
    reg_response = await client.post(
        "/api/v1/auth/register",
        json={
            "email": "refresh@example.com",
            "password": "SecurePass123",
        },
    )
    tokens = reg_response.json()
    refresh_token = tokens["refresh_token"]
    
    # Refresh tokens
    response = await client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": refresh_token},
    )
    
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert "refresh_token" in data
    assert data["access_token"] != tokens["access_token"]  # New token


@pytest.mark.asyncio
async def test_refresh_token_reuse(client: AsyncClient):
    """Test that refresh tokens cannot be reused (token rotation)."""
    # Register and get tokens
    reg_response = await client.post(
        "/api/v1/auth/register",
        json={
            "email": "reuse@example.com",
            "password": "SecurePass123",
        },
    )
    tokens = reg_response.json()
    refresh_token = tokens["refresh_token"]
    
    # Use refresh token once
    response1 = await client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": refresh_token},
    )
    assert response1.status_code == 200
    
    # Try to reuse the same refresh token
    response2 = await client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": refresh_token},
    )
    assert response2.status_code == 401


@pytest.mark.asyncio
async def test_logout(client: AsyncClient):
    """Test user logout."""
    # Register and get tokens
    reg_response = await client.post(
        "/api/v1/auth/register",
        json={
            "email": "logout@example.com",
            "password": "SecurePass123",
        },
    )
    tokens = reg_response.json()
    refresh_token = tokens["refresh_token"]
    
    # Logout
    response = await client.post(
        "/api/v1/auth/logout",
        json={"refresh_token": refresh_token},
    )
    
    assert response.status_code == 200
    assert "logged out" in response.json()["message"].lower()
    
    # Try to use the refresh token after logout
    refresh_response = await client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": refresh_token},
    )
    assert refresh_response.status_code == 401


@pytest.mark.asyncio
async def test_change_password(client: AsyncClient):
    """Test password change."""
    # Register and get tokens
    reg_response = await client.post(
        "/api/v1/auth/register",
        json={
            "email": "changepass@example.com",
            "password": "OldPassword123",
        },
    )
    tokens = reg_response.json()
    access_token = tokens["access_token"]
    
    # Change password
    response = await client.post(
        "/api/v1/auth/change-password",
        json={
            "current_password": "OldPassword123",
            "new_password": "NewPassword456",
        },
        headers={"Authorization": f"Bearer {access_token}"},
    )
    
    assert response.status_code == 200
    
    # Verify old password no longer works
    login_old = await client.post(
        "/api/v1/auth/login",
        json={
            "email": "changepass@example.com",
            "password": "OldPassword123",
        },
    )
    assert login_old.status_code == 401
    
    # Verify new password works
    login_new = await client.post(
        "/api/v1/auth/login",
        json={
            "email": "changepass@example.com",
            "password": "NewPassword456",
        },
    )
    assert login_new.status_code == 200

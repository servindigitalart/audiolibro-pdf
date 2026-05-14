import pytest
from httpx import AsyncClient
from app.main import app

BASE_URL = "http://127.0.0.1:8000"

@pytest.mark.asyncio
async def test_auth_flow():

    async with AsyncClient(app=app, base_url=BASE_URL) as client:

        email = "test_auto@mail.com"
        password = "Test12345!"

        # REGISTER
        r = await client.post("/api/v1/auth/register", json={
            "email": email,
            "password": password
        })

        assert r.status_code in [200, 201]
        data = r.json()
        assert "access_token" in data

        token = data["access_token"]

        # LOGIN
        r2 = await client.post("/api/v1/auth/login", json={
            "email": email,
            "password": password
        })

        assert r2.status_code == 200

        # ME
        r3 = await client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {token}"}
        )

        assert r3.status_code == 200

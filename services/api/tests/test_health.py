"""
Integration Tests: /api/v1/health and /api/v1/
===============================================
Health check tests are environment-aware:
- Redis is always mocked → redis service always reports "healthy".
- DB uses the production engine singleton (app.db.session.engine), which
  points to whatever DATABASE_ASYNC_URL is set to.  In CI this is
  sonoro_test, so the DB check also passes.  Outside CI (local dev without
  Docker) the DB check may report unhealthy — that's fine, we only assert
  on structure and Redis status.

The root endpoint ( GET /api/v1/ ) has no external dependencies and must
always return 200.
"""

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.integration


# ── Root endpoint ─────────────────────────────────────────────────────────────

async def test_root_endpoint_returns_200(client: AsyncClient):
    r = await client.get("/api/v1/")
    assert r.status_code == 200


async def test_root_endpoint_body(client: AsyncClient):
    r = await client.get("/api/v1/")
    data = r.json()
    assert data["service"] == "sonoro-api"
    assert data["status"] == "running"
    assert "version" in data
    assert "environment" in data


# ── Health endpoint ───────────────────────────────────────────────────────────

def _extract_health(r) -> dict:
    """
    Return the health payload regardless of status code.
    200 → body is the payload directly.
    503 → FastAPI wraps it as {"detail": <payload>}.
    """
    if r.status_code == 200:
        return r.json()
    return r.json()["detail"]


async def test_health_returns_200_or_503(client: AsyncClient):
    r = await client.get("/api/v1/health")
    assert r.status_code in (200, 503)


async def test_health_top_level_structure(client: AsyncClient):
    r = await client.get("/api/v1/health")
    data = _extract_health(r)

    assert "status" in data
    assert data["status"] in ("healthy", "unhealthy")
    assert "environment" in data
    assert "services" in data


async def test_health_services_keys_present(client: AsyncClient):
    r = await client.get("/api/v1/health")
    services = _extract_health(r)["services"]

    assert "database" in services
    assert "redis" in services


async def test_health_each_service_has_status_field(client: AsyncClient):
    r = await client.get("/api/v1/health")
    services = _extract_health(r)["services"]

    for name, info in services.items():
        assert "status" in info, f"service '{name}' missing 'status' key"
        assert info["status"] in ("healthy", "unhealthy")


async def test_redis_always_healthy_in_tests(client: AsyncClient):
    """FakeRedis.ping() always returns True, so redis must be healthy."""
    r = await client.get("/api/v1/health")
    services = _extract_health(r)["services"]
    assert services["redis"]["status"] == "healthy"

"""
Health Endpoint Tests
=====================
Test health check endpoints.
"""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_root_endpoint(client: AsyncClient):
    """Test root endpoint returns basic info."""
    response = await client.get("/api/v1/")
    assert response.status_code == 200
    data = response.json()
    assert data["service"] == "sonoro-api"
    assert data["status"] == "running"
    assert "version" in data


@pytest.mark.asyncio
async def test_health_check_success(client: AsyncClient):
    """Test health check endpoint when all services are healthy."""
    response = await client.get("/api/v1/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert "services" in data
    assert "database" in data["services"]
    assert "redis" in data["services"]


@pytest.mark.asyncio
async def test_health_check_structure(client: AsyncClient):
    """Test health check response structure."""
    response = await client.get("/api/v1/health")
    data = response.json()

    # Check top-level keys
    assert "status" in data
    assert "environment" in data
    assert "services" in data

    # Check services structure
    services = data["services"]
    for service_name in ["database", "redis"]:
        assert service_name in services
        assert "status" in services[service_name]
        assert services[service_name]["status"] in ["healthy", "unhealthy"]

import pytest
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient

from app.main import app


def test_api_v1_health_endpoint():
    client = TestClient(app)
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "MindMesh API",
    }


def test_legacy_health_endpoint_compatibility():
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "MindMesh API",
    }


def test_cors_headers():
    client = TestClient(app)
    response = client.get(
        "/api/v1/health",
        headers={"Origin": "http://localhost:3000"},
    )
    assert response.status_code == 200
    assert response.headers.get("access-control-allow-origin") == "http://localhost:3000"


@pytest.mark.asyncio
async def test_async_api_v1_health_endpoint():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/v1/health")
        assert response.status_code == 200
        assert response.json() == {
            "status": "ok",
            "service": "MindMesh API",
        }

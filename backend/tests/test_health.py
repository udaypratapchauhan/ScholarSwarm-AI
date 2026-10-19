"""Unit tests for the FastAPI /api/health endpoint.

Tests both healthy (200 OK) and simulated unhealthy (503 Service Unavailable)
states using FastAPI TestClient.
"""

from fastapi.testclient import TestClient
import pytest

from backend.app.database import set_simulate_db_failure
from backend.app.main import app


@pytest.fixture
def client():
    """Create test client for FastAPI application."""
    with TestClient(app) as test_client:
        yield test_client


def test_health_endpoint_healthy(client: TestClient):
    """Verify health endpoint returns 200 OK and connected status under normal conditions."""
    set_simulate_db_failure(False)
    response = client.get("/api/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert data["database"] == "connected"
    assert data["version"] == "0.1.0"
    assert "timestamp" in data


def test_health_endpoint_unhealthy_simulation(client: TestClient):
    """Verify health endpoint returns 503 Service Unavailable when database connectivity fails."""
    try:
        # Simulate database failure
        set_simulate_db_failure(True)
        response = client.get("/api/health")
        assert response.status_code == 503
        data = response.json()
        assert data["status"] == "unhealthy"
        assert data["database"] == "disconnected"
        assert data["version"] == "0.1.0"
        assert "timestamp" in data
    finally:
        # Reset state immediately to prevent polluting other tests
        set_simulate_db_failure(False)

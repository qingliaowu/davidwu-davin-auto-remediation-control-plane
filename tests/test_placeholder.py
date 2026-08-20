"""Placeholder tests until real behavior is implemented."""

from fastapi.testclient import TestClient

from auto_remediation.main import app


def test_health():
    """Health endpoint returns ok."""
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}

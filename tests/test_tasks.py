"""Tests for the remediation task endpoints."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_get_missing_task(client: TestClient) -> None:
    """Fetching an unknown task returns 404."""
    response = client.get("/tasks/not-a-task")
    assert response.status_code == 404


def test_list_tasks_is_a_list(client: TestClient) -> None:
    """The tasks list endpoint returns a tasks array."""
    response = client.get("/tasks")
    assert response.status_code == 200
    assert response.json() == {"tasks": []}

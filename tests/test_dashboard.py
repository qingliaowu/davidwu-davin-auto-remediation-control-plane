"""Tests for the dashboard routes and event store."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from auto_remediation.main import app
from auto_remediation.store import store


def test_dashboard_renders() -> None:
    """Dashboard endpoint returns HTML."""
    client = TestClient(app)
    response = client.get("/dashboard")
    assert response.status_code == 200
    assert "Auto Remediation Control Plane" in response.text


def test_api_events_lists_dispatches(monkeypatch: pytest.MonkeyPatch) -> None:
    """API events endpoint returns recorded remediation events."""
    monkeypatch.setattr("auto_remediation.main.settings.webhook_secret", None)
    client = TestClient(app)

    event = {
        "status": "dispatched",
        "owner": "owner",
        "repo": "repo",
        "issue_number": 1,
        "session_id": "devin-123",
    }
    # Clear and seed the global store for a deterministic test
    store._events.clear()
    store._events.append(event)

    response = client.get("/api/events")
    assert response.status_code == 200
    assert response.json() == {"events": [event]}

"""Tests for the GitHub webhook endpoint."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from auto_remediation.main import app
from tests.test_devin_client import MockAsyncClient


def test_health() -> None:
    """Health endpoint returns ok."""
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_github_webhook_ignores_unsupported_actions() -> None:
    """Unsupported issue actions are ignored."""
    client = TestClient(app)
    payload = {
        "action": "closed",
        "issue": {"number": 1, "title": "Bug", "body": "Details"},
        "repository": {"full_name": "owner/repo"},
    }
    response = client.post("/webhook/github", json=payload)
    assert response.status_code == 200
    assert response.json() == {"status": "ignored", "action": "closed"}


def test_github_webhook_dispatches_to_devin(monkeypatch: pytest.MonkeyPatch) -> None:
    """An opened issue creates a Devin session and returns session details."""
    monkeypatch.setattr("auto_remediation.devin_client.settings.devin_api_key", "cog_key")
    monkeypatch.setattr("auto_remediation.devin_client.settings.devin_org_id", "org-123")

    mock_response = {
        "session_id": "devin-abc",
        "url": "https://app.devin.ai/sessions/devin-abc",
        "status": "running",
    }

    with patch("httpx.AsyncClient", return_value=MockAsyncClient(response=mock_response)):
        client = TestClient(app)
        payload = {
            "action": "opened",
            "issue": {"number": 42, "title": "Fix login", "body": "Users cannot log in."},
            "repository": {"full_name": "owner/repo"},
        }
        response = client.post("/webhook/github", json=payload)

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "dispatched"
    assert data["session_id"] == "devin-abc"
    assert data["session_url"] == "https://app.devin.ai/sessions/devin-abc"

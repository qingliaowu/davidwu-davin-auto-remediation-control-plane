"""Tests for the Devin API client."""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import httpx
import pytest

from auto_remediation.devin_client import DevinClient, DevinClientError


class MockAsyncClient:
    """Minimal async httpx client mock."""

    def __init__(self, response: dict[str, Any] | None = None, status: int = 200) -> None:
        self.response = response or {}
        self.status = status

    async def __aenter__(self) -> "MockAsyncClient":
        return self

    async def __aexit__(self, *args: object) -> bool:
        return False

    async def post(self, *args: Any, **kwargs: Any) -> httpx.Response:
        return httpx.Response(self.status, json=self.response)

    async def get(self, *args: Any, **kwargs: Any) -> httpx.Response:
        return httpx.Response(self.status, json=self.response)


def test_devin_client_requires_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """DevinClient raises if API key is missing."""
    monkeypatch.setattr("auto_remediation.devin_client.settings.devin_api_key", None)
    monkeypatch.setattr("auto_remediation.devin_client.settings.devin_org_id", "org-123")

    with pytest.raises(DevinClientError, match="Devin API key"):
        DevinClient()


def test_devin_client_requires_org_id(monkeypatch: pytest.MonkeyPatch) -> None:
    """DevinClient raises if organization ID is missing."""
    monkeypatch.setattr("auto_remediation.devin_client.settings.devin_api_key", "cog_key")
    monkeypatch.setattr("auto_remediation.devin_client.settings.devin_org_id", None)

    with pytest.raises(DevinClientError, match="Devin organization ID"):
        DevinClient()


@pytest.mark.anyio
async def test_create_session(monkeypatch: pytest.MonkeyPatch) -> None:
    """DevinClient.create_session posts the correct payload and returns the response."""
    monkeypatch.setattr("auto_remediation.devin_client.settings.devin_api_key", "cog_key")
    monkeypatch.setattr("auto_remediation.devin_client.settings.devin_org_id", "org-123")

    mock_response = {
        "session_id": "devin-abc",
        "url": "https://app.devin.ai/sessions/devin-abc",
        "status": "running",
    }

    with patch("httpx.AsyncClient", return_value=MockAsyncClient(response=mock_response)):
        client = DevinClient()
        result = await client.create_session("Fix login bug", title="Bug fix")

    assert result["session_id"] == "devin-abc"
    assert result["status"] == "running"


@pytest.mark.anyio
async def test_get_session(monkeypatch: pytest.MonkeyPatch) -> None:
    """DevinClient.get_session retrieves a session."""
    monkeypatch.setattr("auto_remediation.devin_client.settings.devin_api_key", "cog_key")
    monkeypatch.setattr("auto_remediation.devin_client.settings.devin_org_id", "org-123")

    mock_response = {"session_id": "devin-abc", "status": "exit"}

    with patch("httpx.AsyncClient", return_value=MockAsyncClient(response=mock_response)):
        client = DevinClient()
        result = await client.get_session("devin-abc")

    assert result["status"] == "exit"

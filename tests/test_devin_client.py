"""Tests for the typed async Devin v3 HTTPX client."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import httpx
import pytest

from auto_remediation.devin_client import DevinClient, DevinClientError


class FakeResponse:
    """A minimal httpx response stand-in."""

    def __init__(self, status_code: int, json_data: Any | None = None) -> None:
        self.status_code = status_code
        self._json = json_data

    def json(self) -> Any:
        return self._json

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                "error",
                request=httpx.Request("GET", "https://api.devin.ai"),
                response=self,
            )


class FakeAsyncClient:
    """A fake httpx.AsyncClient that returns queued responses."""

    responses: list[Any] = []
    calls: list[tuple[str, str]] = []

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        pass

    @classmethod
    def with_responses(cls, responses: list[Any]) -> type["FakeAsyncClient"]:
        """Return the class after loading response queue and resetting call state."""
        cls.responses = list(responses)
        cls.calls = []
        return cls

    async def __aenter__(self) -> "FakeAsyncClient":
        return self

    async def __aexit__(self, *args: Any) -> None:
        pass

    async def get(self, url: str, headers: dict[str, str] | None = None) -> Any:
        FakeAsyncClient.calls.append(("GET", url))
        return FakeAsyncClient.responses.pop(0)

    async def post(self, url: str, headers: dict[str, str] | None = None, json: Any = None) -> Any:
        FakeAsyncClient.calls.append(("POST", url))
        return FakeAsyncClient.responses.pop(0)


@pytest.fixture
def patched_client(monkeypatch: pytest.MonkeyPatch) -> Callable[[list[Any]], type[FakeAsyncClient]]:
    """Install FakeAsyncClient for the duration of a test."""

    def _make(responses: list[Any]) -> type[FakeAsyncClient]:
        FakeAsyncClient.with_responses(responses)
        monkeypatch.setattr("auto_remediation.devin_client.httpx.AsyncClient", FakeAsyncClient)
        return FakeAsyncClient

    return _make


@pytest.mark.asyncio
async def test_create_session_success(
    patched_client: Callable[[list[Any]], type[FakeAsyncClient]],
    devin_client: DevinClient,
) -> None:
    """Successful session creation returns the exact opaque session_id."""
    patched_client(
        [
            FakeResponse(
                201,
                {
                    "session_id": "sess_abc-123",
                    "url": "https://app.devin.ai/sessions/sess_abc-123",
                    "status": "running",
                },
            )
        ]
    )
    result = await devin_client.create_session("prompt", "title", ["tag"])
    assert result["session_id"] == "sess_abc-123"
    assert result["url"] == "https://app.devin.ai/sessions/sess_abc-123"


@pytest.mark.asyncio
async def test_create_session_exact_id_no_prefix(
    patched_client: Callable[[list[Any]], type[FakeAsyncClient]],
    devin_client: DevinClient,
) -> None:
    """The client preserves the exact session_id returned by Devin without adding a prefix."""
    patched_client(
        [
            FakeResponse(
                201,
                {
                    "session_id": "devin_session_42",
                    "url": "https://app.devin.ai/sessions/devin_session_42",
                    "status": "running",
                },
            )
        ]
    )
    result = await devin_client.create_session("prompt", "title", ["tag"])
    assert result["session_id"] == "devin_session_42"


@pytest.mark.asyncio
async def test_create_session_auth_failure(
    patched_client: Callable[[list[Any]], type[FakeAsyncClient]],
    devin_client: DevinClient,
) -> None:
    """A 401 response is surfaced as a sanitized DevinClientError and not retried."""
    patched_client([FakeResponse(401, {"detail": "unauthorized"})])
    with pytest.raises(DevinClientError) as exc:
        await devin_client.create_session("prompt", "title", ["tag"])
    assert exc.value.status_code == 401
    assert FakeAsyncClient.calls == [
        ("POST", "https://api.devin.ai/v3/organizations/test-org/sessions")
    ]


@pytest.mark.asyncio
async def test_create_session_rate_limit_retries(
    patched_client: Callable[[list[Any]], type[FakeAsyncClient]],
    devin_client: DevinClient,
) -> None:
    """A 429 response is retried for POST /sessions and eventually succeeds."""
    patched_client(
        [
            FakeResponse(429, {"detail": "rate limited"}),
            FakeResponse(
                201,
                {
                    "session_id": "sess_after_429",
                    "url": "https://app.devin.ai/sessions/sess_after_429",
                    "status": "running",
                },
            ),
        ],
    )
    result = await devin_client.create_session("prompt", "title", ["tag"])
    assert result["session_id"] == "sess_after_429"
    assert len(FakeAsyncClient.calls) == 2


@pytest.mark.asyncio
async def test_get_session_retry_on_500(
    patched_client: Callable[[list[Any]], type[FakeAsyncClient]],
    devin_client: DevinClient,
) -> None:
    """GET /sessions/{id} retries on a 500 error and preserves the exact session_id."""
    session_id = "sess_get_123"
    patched_client(
        [
            FakeResponse(500, {"detail": "server error"}),
            FakeResponse(
                200,
                {
                    "session_id": session_id,
                    "url": "https://app.devin.ai/sessions/sess_get_123",
                    "status": "running",
                },
            ),
        ],
    )
    result = await devin_client.get_session(session_id)
    assert result["session_id"] == session_id
    assert len(FakeAsyncClient.calls) == 2


@pytest.mark.asyncio
async def test_create_session_post_timeout_no_duplicate(
    patched_client: Callable[[list[Any]], type[FakeAsyncClient]],
    devin_client: DevinClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An ambiguous POST timeout is not retried, avoiding duplicate Devin sessions."""

    class TimeoutClient(FakeAsyncClient):
        async def post(
            self, url: str, headers: dict[str, str] | None = None, json: Any = None
        ) -> Any:
            FakeAsyncClient.calls.append(("POST", url))
            raise httpx.TimeoutException("POST timed out")

    patched_client([])
    monkeypatch.setattr("auto_remediation.devin_client.httpx.AsyncClient", TimeoutClient)

    with pytest.raises(DevinClientError):
        await devin_client.create_session("prompt", "title", ["tag"])

    assert len(FakeAsyncClient.calls) == 1


@pytest.mark.asyncio
async def test_get_session_preserves_opaque_id(
    patched_client: Callable[[list[Any]], type[FakeAsyncClient]],
    devin_client: DevinClient,
) -> None:
    """The client stores and returns the exact opaque session_id."""
    session_id = "opaque-id-with-dashes_and.dots:123"
    patched_client([FakeResponse(200, {"session_id": session_id, "status": "running"})])
    result = await devin_client.get_session(session_id)
    assert result["session_id"] == session_id

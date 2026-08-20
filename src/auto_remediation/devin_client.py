"""Async client for the Devin v3 API."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any, AsyncGenerator

import httpx

from auto_remediation.config import settings


class DevinClientError(Exception):
    """Raised when the Devin API returns an error or the client is misconfigured."""


class DevinClient:
    """Thin async wrapper around the Devin v3 sessions API."""

    def __init__(
        self,
        api_key: str | None = None,
        org_id: str | None = None,
        base_url: str | None = None,
        create_as_user_id: str | None = None,
    ) -> None:
        self.api_key = api_key or settings.devin_api_key
        self.org_id = org_id or settings.devin_org_id
        self.base_url = (base_url or settings.devin_base_url or "https://api.devin.ai/v3").rstrip(
            "/"
        )
        self.create_as_user_id = create_as_user_id or settings.devin_create_as_user_id

        if not self.api_key:
            raise DevinClientError("Devin API key is not configured (ARP_DEVIN_API_KEY)")
        if not self.org_id:
            raise DevinClientError("Devin organization ID is not configured (ARP_DEVIN_ORG_ID)")

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    @asynccontextmanager
    async def _client(self) -> AsyncGenerator[httpx.AsyncClient, None]:
        async with httpx.AsyncClient(base_url=self.base_url, headers=self._headers()) as client:
            yield client

    async def create_session(
        self,
        prompt: str,
        title: str | None = None,
        create_as_user_id: str | None = None,
    ) -> dict[str, Any]:
        """Create a new Devin session with the given prompt."""
        payload: dict[str, Any] = {"prompt": prompt}
        if title:
            payload["title"] = title
        if create_as_user_id or self.create_as_user_id:
            payload["create_as_user_id"] = create_as_user_id or self.create_as_user_id

        async with self._client() as client:
            response = await client.post(
                f"/organizations/{self.org_id}/sessions",
                json=payload,
            )
            return self._parse_response(response)

    async def get_session(self, session_id: str) -> dict[str, Any]:
        """Retrieve the current state of a Devin session."""
        async with self._client() as client:
            response = await client.get(f"/organizations/{self.org_id}/sessions/{session_id}")
            return self._parse_response(response)

    async def list_messages(self, session_id: str) -> dict[str, Any]:
        """List messages for a Devin session."""
        async with self._client() as client:
            response = await client.get(
                f"/organizations/{self.org_id}/sessions/{session_id}/messages"
            )
            return self._parse_response(response)

    async def list_attachments(self, session_id: str) -> dict[str, Any]:
        """List attachments for a Devin session."""
        async with self._client() as client:
            response = await client.get(
                f"/organizations/{self.org_id}/sessions/{session_id}/attachments"
            )
            return self._parse_response(response)

    def _parse_response(self, response: httpx.Response) -> dict[str, Any]:
        """Return JSON body or raise a DevinClientError for HTTP errors."""
        if response.status_code >= 400:
            raise DevinClientError(f"Devin API error {response.status_code}: {response.text}")
        return response.json()

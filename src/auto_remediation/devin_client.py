"""Async typed client for the Devin v3 API."""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any

import httpx

from auto_remediation.config import settings

logger = logging.getLogger(__name__)

_DEVIN_TIMEOUT = httpx.Timeout(connect=10.0, read=30.0, write=30.0, pool=5.0)
_MAX_RETRIES = 3
_RETRY_BACKOFF = 1.0

STRUCTURED_OUTPUT_SCHEMA: dict[str, Any] = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "type": "object",
    "required": [
        "outcome",
        "issue_number",
        "summary",
        "branch",
        "commit_sha",
        "pr_url",
        "changed_files",
        "verification",
        "blockers",
    ],
    "properties": {
        "outcome": {"type": "string", "enum": ["success", "failed", "no_change"]},
        "issue_number": {"type": "integer"},
        "summary": {"type": "string"},
        "branch": {"type": ["string", "null"]},
        "commit_sha": {"type": ["string", "null"]},
        "pr_url": {"type": ["string", "null"]},
        "changed_files": {"type": "array", "items": {"type": "string"}},
        "verification": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["command", "exit_code", "result", "notes", "required"],
                "properties": {
                    "command": {"type": "string"},
                    "exit_code": {"type": ["integer", "null"]},
                    "result": {"type": "string", "enum": ["passed", "failed", "not_run"]},
                    "notes": {"type": "string"},
                    "required": {"type": "boolean"},
                },
            },
        },
        "blockers": {"type": "array", "items": {"type": "string"}},
    },
}


class DevinClientError(Exception):
    """Raised when the Devin API returns an error or the request fails."""

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


class DevinClient:
    """Typed async HTTPX client for Devin v3."""

    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        org_id: str | None = None,
        dry_run: bool | None = None,
    ) -> None:
        self.base_url = (base_url or settings.devin_api_base_url).rstrip("/")
        self.api_key = api_key or settings.devin_api_key
        self.org_id = org_id or settings.devin_org_id
        self.dry_run = dry_run if dry_run is not None else settings.devin_dry_run
        self.timeout = _DEVIN_TIMEOUT

    def _headers(self) -> dict[str, str]:
        if not self.api_key:
            raise DevinClientError("Devin API key is not configured", status_code=401)
        return {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}

    def _url(self, path: str) -> str:
        return f"{self.base_url}{path}"

    @staticmethod
    def _sanitize_error(exc: httpx.HTTPError) -> str:
        """Return a safe error message that never contains headers or keys."""
        if isinstance(exc, httpx.HTTPStatusError):
            return f"Devin API returned {exc.response.status_code}"
        return f"Devin API request failed: {type(exc).__name__}"

    async def _request(
        self,
        method: str,
        path: str,
        json_payload: dict[str, Any] | None = None,
        *,
        retry_429: bool = False,
        retry_5xx: bool = False,
        retry_network: bool = False,
    ) -> dict[str, Any]:
        """Make an HTTP request with bounded, safe retries."""
        last_error: Exception | None = None
        attempt = 0
        while attempt < _MAX_RETRIES:
            attempt += 1
            try:
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    if method.upper() == "GET":
                        response = await client.get(self._url(path), headers=self._headers())
                    else:
                        response = await client.post(
                            self._url(path),
                            headers=self._headers(),
                            json=json_payload,
                        )
                    response.raise_for_status()
                    return response.json()
            except httpx.HTTPStatusError as exc:
                status = exc.response.status_code
                if status == 429 and retry_429 and attempt < _MAX_RETRIES:
                    last_error = exc
                    logger.warning("Devin rate limited (429), attempt %s/%s", attempt, _MAX_RETRIES)
                    await asyncio.sleep(_RETRY_BACKOFF * attempt)
                    continue
                if status >= 500 and retry_5xx and attempt < _MAX_RETRIES:
                    last_error = exc
                    logger.warning(
                        "Devin server error %s, attempt %s/%s", status, attempt, _MAX_RETRIES
                    )
                    await asyncio.sleep(_RETRY_BACKOFF * attempt)
                    continue
                logger.error("Devin API error: %s", self._sanitize_error(exc))
                raise DevinClientError(self._sanitize_error(exc), status_code=status) from exc
            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                # Never retry an ambiguous POST timeout/network error that may have already
                # created a Devin session.
                if method.upper() == "POST":
                    logger.error("Devin POST timed out; not retrying to avoid duplicate sessions")
                    raise DevinClientError(self._sanitize_error(exc), status_code=None) from exc
                if retry_network and attempt < _MAX_RETRIES:
                    last_error = exc
                    logger.warning(
                        "Devin %s, attempt %s/%s", type(exc).__name__, attempt, _MAX_RETRIES
                    )
                    await asyncio.sleep(_RETRY_BACKOFF * attempt)
                    continue
                raise DevinClientError(self._sanitize_error(exc), status_code=None) from exc
            except httpx.HTTPError as exc:
                raise DevinClientError(self._sanitize_error(exc), status_code=None) from exc

        raise DevinClientError(
            self._sanitize_error(last_error or DevinClientError("Max retries exceeded"))
        ) from last_error

    def _dry_run_create(self, title: str) -> dict[str, Any]:
        """Return deterministic mock create-session data."""
        session_id = f"dry-run-{uuid.uuid4()}"
        return {
            "session_id": session_id,
            "url": f"https://app.devin.ai/sessions/{session_id}",
            "status": "running",
            "is_dry_run": True,
            "title": title,
        }

    def _dry_run_get(self, session_id: str) -> dict[str, Any]:
        """Return deterministic mock session details."""
        return {
            "session_id": session_id,
            "url": f"https://app.devin.ai/sessions/{session_id}",
            "status": "exit",
            "structured_output": {
                "outcome": "success",
                "issue_number": 42,
                "summary": "Dry-run remediation completed.",
                "branch": "dry-run-branch",
                "commit_sha": "dry-run-commit",
                "pr_url": "https://github.com/dry-run/pull/1",
                "changed_files": ["dry_run.py"],
                "verification": [
                    {
                        "command": "pytest",
                        "exit_code": 0,
                        "result": "passed",
                        "notes": "All tests passed in dry-run mode.",
                        "required": True,
                    },
                ],
                "blockers": [],
            },
            "is_dry_run": True,
        }

    async def create_session(self, prompt: str, title: str, tags: list[str]) -> dict[str, Any]:
        """Create a new Devin remediation session."""
        if self.dry_run:
            return self._dry_run_create(title)

        path = f"/v3/organizations/{self.org_id}/sessions"
        payload: dict[str, Any] = {
            "prompt": prompt,
            "repos": [settings.devin_repo],
            "title": title,
            "tags": tags,
            "devin_mode": settings.devin_mode,
            "max_acu_limit": settings.devin_max_acu_limit,
            "bypass_approval": False,
            "structured_output_required": True,
            "structured_output_schema": STRUCTURED_OUTPUT_SCHEMA,
        }
        # Retry 429 but not ambiguous 5xx/timeouts/network errors.
        result = await self._request("POST", path, json_payload=payload, retry_429=True)
        logger.info("Created Devin session %s", result.get("session_id"))
        return result

    async def get_session(self, session_id: str) -> dict[str, Any]:
        """Fetch details for an existing Devin session."""
        if self.dry_run:
            return self._dry_run_get(session_id)

        path = f"/v3/organizations/{self.org_id}/sessions/{session_id}"
        # Safe to retry GET on 429, 5xx, and network errors.
        return await self._request(
            "GET",
            path,
            retry_429=True,
            retry_5xx=True,
            retry_network=True,
        )

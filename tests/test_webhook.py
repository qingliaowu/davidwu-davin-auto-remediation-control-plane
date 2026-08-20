"""Tests for the GitHub webhook endpoint."""

from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any

from fastapi.testclient import TestClient


def _sign(body: bytes, secret: str) -> str:
    """Compute the GitHub webhook HMAC-SHA256 signature."""
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def _eligible_payload(
    action: str = "labeled",
    label: str = "devin-fix",
    state: str = "open",
    repo: str = "owner/repo",
    issue_number: int = 42,
) -> dict[str, Any]:
    return {
        "action": action,
        "issue": {
            "number": issue_number,
            "title": "Fix login",
            "body": "Users cannot log in.",
            "state": state,
            "html_url": f"https://github.com/{repo}/issues/{issue_number}",
        },
        "repository": {"full_name": repo},
        "label": {"name": label},
    }


def _post_webhook(
    client: TestClient,
    payload: dict[str, Any] | bytes,
    event: str = "issues",
    delivery_id: str = "d1",
    secret: str = "supersecret",
    signature: str | None = None,
) -> Any:
    if isinstance(payload, dict):
        body = json.dumps(payload).encode()
    else:
        body = payload
    sig = signature if signature is not None else _sign(body, secret)
    return client.post(
        "/webhooks/github",
        content=body,
        headers={
            "x-github-event": event,
            "x-github-delivery": delivery_id,
            "x-hub-signature-256": sig,
            "content-type": "application/json",
        },
    )


def test_health(client: TestClient) -> None:
    """Health endpoint returns ok."""
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_valid_signature_creates_task(client: TestClient) -> None:
    """A signed, eligible labeled event creates a QUEUED remediation task."""
    payload = _eligible_payload()
    response = _post_webhook(client, payload)
    assert response.status_code == 202
    data = response.json()
    assert data["status"] == "eligible"
    assert data["delivery_id"] == "d1"
    assert data["repository"] == "owner/repo"
    assert data["issue_number"] == 42
    assert "task_id" in data

    tasks_response = client.get("/tasks")
    assert tasks_response.status_code == 200
    tasks = tasks_response.json()["tasks"]
    assert len(tasks) == 1
    assert tasks[0]["task_id"] == data["task_id"]
    assert tasks[0]["status"] == "QUEUED"
    assert tasks[0]["issue_title"] == "Fix login"


def test_invalid_signature(client: TestClient) -> None:
    """An invalid signature is rejected with 401."""
    payload = _eligible_payload()
    response = _post_webhook(client, payload, signature="sha256=invalid")
    assert response.status_code == 401


def test_malformed_json(client: TestClient) -> None:
    """Malformed JSON body returns 400."""
    body = b"not valid json"
    response = _post_webhook(client, body)
    assert response.status_code == 400


def test_irrelevant_event(client: TestClient) -> None:
    """Non-issues events are ignored with 200."""
    payload = _eligible_payload()
    response = _post_webhook(client, payload, event="push")
    assert response.status_code == 200
    assert response.json()["status"] == "ignored"


def test_wrong_label(client: TestClient) -> None:
    """A labeled event with a non-devin-fix label is ignored."""
    payload = _eligible_payload(label="bug")
    response = _post_webhook(client, payload)
    assert response.status_code == 200
    assert response.json()["status"] == "ignored"


def test_wrong_repository(client: TestClient) -> None:
    """Events from a repository other than the allowed one are ignored."""
    payload = _eligible_payload(repo="other/repo")
    response = _post_webhook(client, payload)
    assert response.status_code == 200
    assert response.json()["status"] == "ignored"


def test_closed_issue(client: TestClient) -> None:
    """Issues that are not open are ignored."""
    payload = _eligible_payload(state="closed")
    response = _post_webhook(client, payload)
    assert response.status_code == 200
    assert response.json()["status"] == "ignored"


def test_duplicate_delivery(client: TestClient) -> None:
    """Duplicate deliveries increment attempt_count and do not create a second task."""
    payload = _eligible_payload()
    first = _post_webhook(client, payload)
    assert first.status_code == 202
    task_id = first.json()["task_id"]

    second = _post_webhook(client, payload)
    assert second.status_code == 200
    assert second.json()["status"] == "duplicate"
    assert second.json()["attempt_count"] == 2

    tasks_response = client.get("/tasks")
    assert tasks_response.status_code == 200
    assert len(tasks_response.json()["tasks"]) == 1
    assert tasks_response.json()["tasks"][0]["task_id"] == task_id


def test_duplicate_delivery_increments_attempt_count(client: TestClient) -> None:
    """Sending the same delivery a third time keeps incrementing the counter."""
    payload = _eligible_payload()
    _post_webhook(client, payload, delivery_id="d3")
    _post_webhook(client, payload, delivery_id="d3")
    third = _post_webhook(client, payload, delivery_id="d3")
    assert third.status_code == 200
    assert third.json()["attempt_count"] == 3

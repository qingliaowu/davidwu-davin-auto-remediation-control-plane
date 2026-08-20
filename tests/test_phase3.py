"""Phase 3 tests for metrics, dashboard, simulator, and secret redaction."""

from __future__ import annotations

import hashlib
import hmac
import json
from datetime import UTC, datetime
from urllib.parse import urlparse

import httpx
import pytest
from fastapi.testclient import TestClient

from auto_remediation.config import Settings
from auto_remediation.devin_client import DevinClient, DevinClientError
from auto_remediation.metrics import get_metrics
from auto_remediation.models import RemediationTask, WebhookDelivery
from auto_remediation.services import verify_signature
from scripts.simulate_webhook import build_payload, run, sign_payload


def _make_delivery(
    github_delivery_id: str = "d1",
    outcome: str = "eligible",
    attempt_count: int = 1,
    issue_number: int = 1,
    repository: str = "owner/repo",
) -> WebhookDelivery:
    return WebhookDelivery(
        github_delivery_id=github_delivery_id,
        event_name="issues",
        action="labeled",
        repository=repository,
        issue_number=issue_number,
        outcome=outcome,
        attempt_count=attempt_count,
        received_at=datetime.now(UTC),
    )


def _make_task(
    delivery: WebhookDelivery,
    status: str = "QUEUED",
    dry_run: bool = False,
    duration: float | None = None,
    acus: float | None = None,
    pr_url: str | None = None,
    session_id: str | None = None,
) -> RemediationTask:
    return RemediationTask(
        webhook_delivery_id=delivery.id,
        repository=delivery.repository or "owner/repo",
        issue_number=delivery.issue_number or 1,
        issue_title="Fix login",
        target_branch="main",
        triggering_label="devin-fix",
        status=status,
        dry_run=dry_run,
        duration_seconds=duration,
        acus_consumed=acus,
        pull_request_url=pr_url,
        devin_session_id=session_id,
    )


async def test_metrics_calculations(db_session) -> None:
    """Metrics reflect delivery attempts, task states, durations, and ACUs."""
    d1 = _make_delivery("d1", "eligible", attempt_count=1)
    d2 = _make_delivery("d2", "ignored", attempt_count=1)
    d3 = _make_delivery("d3", "eligible", attempt_count=3)
    d4 = _make_delivery("d4", "eligible", attempt_count=1)
    db_session.add_all([d1, d2, d3, d4])
    await db_session.flush()

    t1 = _make_task(
        d1,
        "SUCCEEDED",
        duration=120.0,
        acus=2.5,
        pr_url="https://github.com/pr/1",
        session_id="s1",
    )
    t2 = _make_task(d2, "FAILED", duration=60.0, session_id="s2")
    t3 = _make_task(d3, "RUNNING", session_id="s3")
    t4 = _make_task(d4, "WAITING_FOR_USER", session_id="s4")
    db_session.add_all([t1, t2, t3, t4])
    await db_session.commit()

    metrics = await get_metrics(db_session)

    assert metrics["webhook_delivery_attempts"] == 6  # 1 + 1 + 3 + 1
    assert metrics["unique_webhook_deliveries"] == 4
    assert metrics["duplicate_attempts"] == 2
    assert metrics["eligible_tasks"] == 4
    assert metrics["ignored_events"] == 1
    assert metrics["devin_sessions_created"] == 4
    assert metrics["active_tasks"] == 2  # RUNNING + WAITING_FOR_USER
    assert metrics["waiting_tasks"] == 1
    assert metrics["successful_tasks"] == 1
    assert metrics["failed_tasks"] == 1
    assert metrics["pull_requests_created"] == 1
    assert metrics["success_rate"] == 0.5
    assert metrics["success_rate_percent"] == 50.0
    assert metrics["average_successful_task_duration_seconds"] == 120.0
    assert metrics["total_acus_consumed"] == 2.5


def test_metrics_endpoint_empty(client: TestClient) -> None:
    """/metrics returns zeroed metrics when the database is empty."""
    response = client.get("/metrics")
    assert response.status_code == 200
    data = response.json()
    assert data["webhook_delivery_attempts"] == 0
    assert data["eligible_tasks"] == 0
    assert data["success_rate"] == 0.0
    assert "success_rate_percent" in data


def test_dashboard_dry_run_labeling(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """The dashboard marks dry-run tasks with a DRY RUN badge."""
    new_settings = Settings(
        github_webhook_secret="supersecret",
        github_allowed_repository="owner/repo",
        devin_dry_run=True,
    )
    monkeypatch.setattr("auto_remediation.config.settings", new_settings)
    monkeypatch.setattr("auto_remediation.services.settings", new_settings)

    payload = {
        "action": "labeled",
        "issue": {
            "number": 99,
            "title": "Dry run issue",
            "body": "test",
            "state": "open",
            "html_url": "https://github.com/owner/repo/issues/99",
        },
        "repository": {"full_name": "owner/repo"},
        "label": {"name": "devin-fix"},
    }
    body = json.dumps(payload).encode()
    sig = "sha256=" + hmac.new(b"supersecret", body, hashlib.sha256).hexdigest()

    post = client.post(
        "/webhooks/github",
        content=body,
        headers={
            "x-github-event": "issues",
            "x-github-delivery": "dry-run-delivery",
            "x-hub-signature-256": sig,
            "content-type": "application/json",
        },
    )
    assert post.status_code == 202

    response = client.get("/dashboard")
    assert response.status_code == 200
    html = response.text
    assert "Dry run issue" in html
    assert "DRY RUN" in html
    assert "#99" in html


def test_dashboard_task_detail(client: TestClient) -> None:
    """Task detail page renders issue metadata and status."""
    payload = {
        "action": "labeled",
        "issue": {
            "number": 77,
            "title": "Detail test",
            "body": "body",
            "state": "open",
            "html_url": "https://github.com/owner/repo/issues/77",
        },
        "repository": {"full_name": "owner/repo"},
        "label": {"name": "devin-fix"},
    }
    body = json.dumps(payload).encode()
    sig = "sha256=" + hmac.new(b"supersecret", body, hashlib.sha256).hexdigest()

    post = client.post(
        "/webhooks/github",
        content=body,
        headers={
            "x-github-event": "issues",
            "x-github-delivery": "detail-delivery",
            "x-hub-signature-256": sig,
            "content-type": "application/json",
        },
    )
    assert post.status_code == 202
    task_id = post.json()["task_id"]

    response = client.get(f"/dashboard/tasks/{task_id}")
    assert response.status_code == 200
    html = response.text
    assert "Detail test" in html
    assert "#77" in html
    assert task_id[:8] in html


def test_simulator_signature_matches_verification() -> None:
    """The simulator signs the exact body bytes accepted by verify_signature."""
    secret = "test-secret"
    payload = build_payload("owner/repo", 42, "Fix login")
    body = json.dumps(payload, separators=(",", ":")).encode()
    signature = sign_payload(body, secret)
    assert signature.startswith("sha256=")
    assert verify_signature(body, secret, signature)
    assert not verify_signature(body, secret, "sha256=invalid")


def test_duplicate_simulator_delivery(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """The simulator sends the same delivery ID twice and the second is a duplicate."""
    responses: list = []

    def fake_post(url: str, **kwargs: object) -> httpx.Response:
        path = urlparse(url).path
        resp = client.post(path, **kwargs)
        responses.append(resp)
        return resp

    monkeypatch.setattr(httpx, "post", fake_post)

    exit_code = run(
        repository="owner/repo",
        issue_number=55,
        issue_title="Duplicate test",
        label="devin-fix",
        secret="supersecret",
        base_url="http://127.0.0.1:8000",
        duplicate=True,
    )
    assert exit_code == 0
    assert len(responses) == 2
    assert responses[0].status_code == 202
    assert responses[1].status_code == 200
    assert responses[1].json()["status"] == "duplicate"
    assert responses[1].json()["attempt_count"] == 2


@pytest.mark.asyncio
async def test_secret_redaction_in_devin_client_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    """DevinClientError messages do not leak the API key."""
    api_key = "super-secret-key-must-not-appear"

    class FakeClient:
        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

        async def __aenter__(self) -> "FakeClient":
            return self

        async def __aexit__(self, *args: object) -> None:
            pass

        async def get(self, *args: object, **kwargs: object) -> httpx.Response:
            request = httpx.Request("GET", "https://api.devin.ai")
            response = httpx.Response(
                500,
                request=request,
                headers={"Authorization": f"Bearer {api_key}"},
            )
            raise httpx.HTTPStatusError("Server error", request=request, response=response)

    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)

    client = DevinClient(
        base_url="https://api.devin.ai",
        api_key=api_key,
        org_id="test-org",
        dry_run=False,
    )

    with pytest.raises(DevinClientError) as exc_info:
        await client.get_session("session-123")

    error = exc_info.value
    assert api_key not in error.message
    assert "Authorization" not in error.message
    assert "500" in error.message

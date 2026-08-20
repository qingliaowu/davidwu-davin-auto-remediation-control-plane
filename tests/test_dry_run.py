"""Tests for dry-run mode."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy import select

from auto_remediation.database import Database
from auto_remediation.devin_client import DevinClient
from auto_remediation.models import RemediationTask, WebhookDelivery
from auto_remediation.worker import Worker


@pytest.mark.asyncio
async def test_dry_run_create_session_does_not_call_api(monkeypatch: pytest.MonkeyPatch) -> None:
    """In dry-run mode create_session returns deterministic mock data without HTTP."""
    httpx_called = False

    class NoOpClient:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            nonlocal httpx_called
            httpx_called = True

        async def __aenter__(self) -> "NoOpClient":
            return self

        async def __aexit__(self, *args: Any) -> None:
            pass

    monkeypatch.setattr("auto_remediation.devin_client.httpx.AsyncClient", NoOpClient)
    client = DevinClient(
        base_url="https://api.devin.ai", api_key="test", org_id="test", dry_run=True
    )

    result = await client.create_session("prompt", "title", ["tag"])

    assert not httpx_called
    assert result["is_dry_run"] is True
    assert result["status"] == "running"
    assert result["session_id"].startswith("dry-run-")


@pytest.mark.asyncio
async def test_dry_run_get_session_returns_terminal_success() -> None:
    """Dry-run get_session returns an exit status with structured success evidence."""
    client = DevinClient(
        base_url="https://api.devin.ai", api_key="test", org_id="test", dry_run=True
    )
    result = await client.get_session("dry-run-123")

    assert result["is_dry_run"] is True
    assert result["status"] == "exit"
    structured = result["structured_output"]
    assert structured["outcome"] == "success"
    assert structured["pr_url"]
    assert structured["verification"][0]["result"] == "passed"


async def _create_queued_task(database: Database) -> None:
    async with database.get_session() as session:
        delivery = WebhookDelivery(
            github_delivery_id="dry-run-delivery",
            event_name="issues",
            action="labeled",
            repository="qingliaowu/superset",
            issue_number=42,
            outcome="eligible",
        )
        session.add(delivery)
        await session.flush()
        task = RemediationTask(
            webhook_delivery_id=delivery.id,
            repository="qingliaowu/superset",
            issue_number=42,
            issue_title="Fix login",
            issue_body="Users cannot log in.",
            issue_url="https://github.com/qingliaowu/superset/issues/42",
            target_branch="main",
            triggering_label="devin-fix",
            status="QUEUED",
            dry_run=True,
            received_at=datetime.now(UTC),
        )
        session.add(task)
        await session.commit()


@pytest.mark.asyncio
async def test_worker_dry_run_transitions_to_succeeded(
    test_database: Database, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A QUEUED dry-run task is dispatched and classified as SUCCEEDED."""
    monkeypatch.setattr("auto_remediation.config.settings.devin_repo", "qingliaowu/superset")
    monkeypatch.setattr("auto_remediation.config.settings.devin_dry_run", True)

    await _create_queued_task(test_database)
    client = DevinClient(
        base_url="https://api.devin.ai", api_key="test", org_id="test", dry_run=True
    )
    worker = Worker(test_database, client)

    # First poll dispatches the dry-run session; second poll finalizes it.
    await worker.poll()
    await worker.poll()

    async with test_database.get_session() as session:
        task = (await session.execute(select(RemediationTask))).scalar_one()
        assert task.status == "SUCCEEDED"
        assert task.dry_run is True
        assert task.devin_session_id is not None
        assert task.devin_session_id.startswith("dry-run-")
        assert task.pull_request_url is not None
        assert task.structured_output is not None
        assert task.structured_output["outcome"] == "success"

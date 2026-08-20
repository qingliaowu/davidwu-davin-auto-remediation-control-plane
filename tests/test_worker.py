"""Tests for the background worker, recovery, and repository concurrency."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy import select

from auto_remediation.database import Database
from auto_remediation.models import RemediationTask, WebhookDelivery
from auto_remediation.worker import Worker


class FakeDevinClient:
    """A fake Devin client that returns deterministic running sessions."""

    def __init__(self, responses: list[dict[str, Any]] | None = None) -> None:
        self.responses = responses or []
        self.calls: list[tuple[str, str]] = []
        self.created_count = 0

    async def create_session(self, prompt: str, title: str, tags: list[str]) -> dict[str, Any]:
        self.created_count += 1
        self.calls.append(("create", ""))
        return {
            "session_id": f"fake-session-{self.created_count}",
            "url": f"https://app.devin.ai/sessions/fake-session-{self.created_count}",
            "status": "running",
        }

    async def get_session(self, session_id: str) -> dict[str, Any]:
        self.calls.append(("get", session_id))
        if self.responses:
            return self.responses.pop(0)
        return {"session_id": session_id, "status": "running"}


async def _create_task(
    database: Database,
    status: str,
    session_id: str | None = None,
    repo: str = "qingliaowu/superset",
) -> str:
    async with database.get_session() as session:
        delivery = WebhookDelivery(
            github_delivery_id=f"delivery-{session_id or status}-{id(session)}",
            event_name="issues",
            action="labeled",
            repository=repo,
            issue_number=42,
            outcome="eligible",
        )
        session.add(delivery)
        await session.flush()
        task = RemediationTask(
            webhook_delivery_id=delivery.id,
            repository=repo,
            issue_number=42,
            issue_title="Fix login",
            issue_body="Users cannot log in.",
            issue_url=f"https://github.com/{repo}/issues/42",
            target_branch="main",
            triggering_label="devin-fix",
            status=status,
            devin_session_id=session_id,
            session_started_at=datetime.now(UTC) if session_id else None,
        )
        session.add(task)
        await session.commit()
        return task.task_id


async def _count_by_status(database: Database, status: str) -> int:
    async with database.get_session() as session:
        result = await session.execute(
            select(RemediationTask).where(RemediationTask.status == status)
        )
        return len(result.scalars().all())


@pytest.mark.asyncio
async def test_recovery_dispatching_without_session_returns_to_queued(
    test_database: Database,
) -> None:
    """A DISPATCHING task with no session_id is rolled back to QUEUED on restart."""
    fake_client = FakeDevinClient()
    worker = Worker(test_database, fake_client)
    await _create_task(test_database, "DISPATCHING")

    await worker.recover()

    assert await _count_by_status(test_database, "QUEUED") == 1
    assert await _count_by_status(test_database, "DISPATCHING") == 0


@pytest.mark.asyncio
async def test_recovery_dispatching_with_session_becomes_running(test_database: Database) -> None:
    """A DISPATCHING task that already has a session_id is marked RUNNING on restart."""
    fake_client = FakeDevinClient()
    worker = Worker(test_database, fake_client)
    await _create_task(test_database, "DISPATCHING", session_id="sess-existing")

    await worker.recover()

    assert await _count_by_status(test_database, "RUNNING") == 1
    assert await _count_by_status(test_database, "DISPATCHING") == 0


@pytest.mark.asyncio
async def test_recovery_queued_with_session_becomes_running(test_database: Database) -> None:
    """A QUEUED task with a session_id resumes as RUNNING after restart."""
    fake_client = FakeDevinClient()
    worker = Worker(test_database, fake_client)
    await _create_task(test_database, "QUEUED", session_id="sess-existing")

    await worker.recover()

    assert await _count_by_status(test_database, "RUNNING") == 1
    assert await _count_by_status(test_database, "QUEUED") == 0


@pytest.mark.asyncio
async def test_repository_concurrency_limit(
    test_database: Database, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Only one task per repository is dispatched when max_concurrent is one."""
    monkeypatch.setattr("auto_remediation.config.settings.devin_repo", "qingliaowu/superset")
    fake_client = FakeDevinClient()
    worker = Worker(test_database, fake_client)
    await _create_task(test_database, "QUEUED")
    await _create_task(test_database, "QUEUED")

    await worker.poll()

    assert fake_client.created_count == 1
    async with test_database.get_session() as session:
        running = (
            (
                await session.execute(
                    select(RemediationTask).where(RemediationTask.status == "RUNNING")
                )
            )
            .scalars()
            .all()
        )
        queued = (
            (
                await session.execute(
                    select(RemediationTask).where(RemediationTask.status == "QUEUED")
                )
            )
            .scalars()
            .all()
        )
        assert len(running) == 1
        assert len(queued) == 1
        assert running[0].devin_session_id is not None
        assert running[0].devin_session_url is not None

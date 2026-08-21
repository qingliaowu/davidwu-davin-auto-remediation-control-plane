"""Tests for Devin session status mapping and final success determination."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy import select

from auto_remediation.database import Database
from auto_remediation.models import RemediationTask, WebhookDelivery
from auto_remediation.worker import Worker


class FakeDevinClient:
    """A fake Devin client that returns queued session responses."""

    def __init__(self, responses: list[dict[str, Any]]) -> None:
        self.responses = responses
        self.calls: list[tuple[str, str]] = []

    async def create_session(self, prompt: str, title: str, tags: list[str]) -> dict[str, Any]:
        self.calls.append(("create", ""))
        return self.responses.pop(0)

    async def get_session(self, session_id: str) -> dict[str, Any]:
        self.calls.append(("get", session_id))
        return self.responses.pop(0)


def _success_structured_output(
    pr_url: str | None = "https://github.com/qingliaowu/superset/pull/1",
) -> dict[str, Any]:
    return {
        "outcome": "success",
        "issue_number": 42,
        "summary": "Fixed the issue",
        "branch": "fix-42",
        "commit_sha": "abc123",
        "pr_url": pr_url,
        "changed_files": ["src/example.py"],
        "verification": [
            {
                "command": "pytest",
                "exit_code": 0,
                "result": "passed",
                "notes": "All tests passed",
            },
        ],
        "blockers": [],
    }


async def _create_running_task(database: Database, session_id: str = "sess-42") -> None:
    async with database.get_session() as session:
        delivery = WebhookDelivery(
            github_delivery_id=f"delivery-{session_id}",
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
            issue_body="Users cannot log in.\nVerification command: pytest",
            issue_url="https://github.com/qingliaowu/superset/issues/42",
            target_branch="main",
            triggering_label="devin-fix",
            status="RUNNING",
            devin_session_id=session_id,
            session_started_at=datetime.now(UTC),
        )
        session.add(task)
        await session.commit()


async def _get_task(database: Database) -> RemediationTask:
    async with database.get_session() as session:
        return (await session.execute(select(RemediationTask))).scalar_one()


@pytest.mark.asyncio
async def test_waiting_for_user(test_database: Database) -> None:
    """Devin status waiting_for_user maps to WAITING_FOR_USER."""
    session_id = "sess-wait-user"
    fake_client = FakeDevinClient([{"status": "waiting_for_user", "session_id": session_id}])
    worker = Worker(test_database, fake_client)
    await _create_running_task(test_database, session_id)

    await worker.poll()

    task = await _get_task(test_database)
    assert task.status == "WAITING_FOR_USER"
    assert task.devin_status == "waiting_for_user"


@pytest.mark.asyncio
async def test_waiting_for_approval(test_database: Database) -> None:
    """Devin status waiting_for_approval maps to WAITING_FOR_APPROVAL."""
    session_id = "sess-wait-approval"
    fake_client = FakeDevinClient([{"status": "waiting_for_approval", "session_id": session_id}])
    worker = Worker(test_database, fake_client)
    await _create_running_task(test_database, session_id)

    await worker.poll()

    task = await _get_task(test_database)
    assert task.status == "WAITING_FOR_APPROVAL"
    assert task.devin_status == "waiting_for_approval"


@pytest.mark.asyncio
async def test_running_status_detail_waiting_for_user(test_database: Database) -> None:
    """A waiting status detail takes precedence over a running lifecycle status."""
    session_id = "sess-detail-wait-user"
    fake_client = FakeDevinClient(
        [{"status": "running", "status_detail": "waiting_for_user", "session_id": session_id}],
    )
    worker = Worker(test_database, fake_client)
    await _create_running_task(test_database, session_id)

    await worker.poll()

    task = await _get_task(test_database)
    assert task.status == "WAITING_FOR_USER"
    assert task.devin_status == "running"
    assert task.devin_status_detail == "waiting_for_user"


@pytest.mark.asyncio
async def test_running_status_detail_waiting_for_approval(test_database: Database) -> None:
    """A waiting-for-approval detail takes precedence over a running status."""
    session_id = "sess-detail-wait-approval"
    fake_client = FakeDevinClient(
        [
            {
                "status": "running",
                "status_detail": "waiting_for_approval",
                "session_id": session_id,
            },
        ],
    )
    worker = Worker(test_database, fake_client)
    await _create_running_task(test_database, session_id)

    await worker.poll()

    task = await _get_task(test_database)
    assert task.status == "WAITING_FOR_APPROVAL"
    assert task.devin_status_detail == "waiting_for_approval"


@pytest.mark.asyncio
async def test_running_status_with_success_evidence_and_supplemental_warning(
    test_database: Database,
) -> None:
    """Complete evidence finalizes a running session with supplemental warnings."""
    session_id = "sess-evidence-warning"
    structured = _success_structured_output()
    structured["verification"] = [
        {
            "command": "ruff check --select RUF012 superset/charts/data/api.py",
            "exit_code": 0,
            "result": "passed",
            "notes": "Ruff passed.",
        },
        {
            "command": "pre-commit run",
            "exit_code": 1,
            "result": "failed",
            "notes": "Known repository-wide mypy failures.",
        },
    ]
    fake_client = FakeDevinClient(
        [
            {
                "status": "running",
                "status_detail": "waiting_for_user",
                "session_id": session_id,
                "structured_output": structured,
            },
        ],
    )
    worker = Worker(test_database, fake_client)
    await _create_running_task(test_database, session_id)
    async with test_database.get_session() as session:
        task = (await session.execute(select(RemediationTask))).scalar_one()
        task.issue_body = (
            "Fix the issue.\nRun `ruff check --select RUF012 superset/charts/data/api.py`."
        )
        await session.commit()

    await worker.poll()

    task = await _get_task(test_database)
    assert task.status == "SUCCEEDED"
    assert task.devin_status == "running"
    assert task.devin_status_detail == "waiting_for_user"
    assert task.verification_status == "passed"
    assert task.verification_summary == "PASSED_WITH_WARNINGS"
    assert task.verification_warnings == [
        {
            "command": "pre-commit run",
            "exit_code": 1,
            "result": "failed",
            "notes": "Known repository-wide mypy failures.",
        },
    ]
    assert task.pull_request_url == "https://github.com/qingliaowu/superset/pull/1"
    assert task.pull_request_number == 1
    assert task.error_code is None


@pytest.mark.asyncio
async def test_successful_completion(test_database: Database) -> None:
    """A terminal Devin status with success evidence marks the task SUCCEEDED."""
    session_id = "sess-success"
    fake_client = FakeDevinClient(
        [
            {
                "status": "exit",
                "session_id": session_id,
                "structured_output": _success_structured_output(),
            },
        ],
    )
    worker = Worker(test_database, fake_client)
    await _create_running_task(test_database, session_id)

    await worker.poll()

    task = await _get_task(test_database)
    assert task.status == "SUCCEEDED"
    assert task.pull_request_url == "https://github.com/qingliaowu/superset/pull/1"
    assert task.pull_request_number == 1
    assert task.verification_status == "passed"
    assert task.verification_summary == "PASSED"
    assert task.structured_output is not None
    assert task.structured_output["outcome"] == "success"


@pytest.mark.asyncio
async def test_completion_without_pull_request(test_database: Database) -> None:
    """Success outcome without a real PR URL is classified as FAILED."""
    session_id = "sess-no-pr"
    fake_client = FakeDevinClient(
        [
            {
                "status": "exit",
                "session_id": session_id,
                "structured_output": _success_structured_output(pr_url=None),
            },
        ],
    )
    worker = Worker(test_database, fake_client)
    await _create_running_task(test_database, session_id)

    await worker.poll()

    task = await _get_task(test_database)
    assert task.status == "FAILED"
    assert task.verification_summary == "FAILED"
    assert task.error_code == "no_pull_request"
    assert task.pull_request_url is None


@pytest.mark.asyncio
async def test_failed_verification(test_database: Database) -> None:
    """A failed verification item results in FAILED even with a PR URL."""
    session_id = "sess-failed-verify"
    structured = _success_structured_output()
    structured["verification"][0]["result"] = "failed"
    structured["verification"][0]["notes"] = "Tests failed"
    fake_client = FakeDevinClient(
        [
            {
                "status": "exit",
                "session_id": session_id,
                "structured_output": structured,
            },
        ],
    )
    worker = Worker(test_database, fake_client)
    await _create_running_task(test_database, session_id)

    await worker.poll()

    task = await _get_task(test_database)
    assert task.status == "FAILED"
    assert task.verification_status == "failed"
    assert task.verification_summary == "FAILED"
    assert task.error_code == "verification_failed"


@pytest.mark.asyncio
async def test_explicit_required_flags_override_issue_body_heuristic(
    test_database: Database,
) -> None:
    """Explicit required flags override command matching against the issue body."""
    session_id = "sess-explicit-required"
    structured = _success_structured_output()
    structured["verification"] = [
        {
            "command": "pytest",
            "exit_code": 1,
            "result": "failed",
            "notes": "Supplemental check failed.",
            "required": False,
        },
        {
            "command": "lint",
            "exit_code": 0,
            "result": "passed",
            "notes": "Required check passed.",
            "required": True,
        },
    ]
    fake_client = FakeDevinClient(
        [
            {
                "status": "exit",
                "session_id": session_id,
                "structured_output": structured,
            },
        ],
    )
    worker = Worker(test_database, fake_client)
    await _create_running_task(test_database, session_id)

    await worker.poll()

    task = await _get_task(test_database)
    assert task.status == "SUCCEEDED"
    assert task.verification_status == "passed"
    assert task.verification_summary == "PASSED_WITH_WARNINGS"
    assert task.verification_warnings is not None
    assert task.verification_warnings[0]["command"] == "pytest"


@pytest.mark.asyncio
async def test_suspended_with_valid_success_evidence(test_database: Database) -> None:
    """A suspended status with valid success evidence still marks SUCCEEDED."""
    session_id = "sess-suspended-success"
    fake_client = FakeDevinClient(
        [
            {
                "status": "suspended",
                "session_id": session_id,
                "structured_output": _success_structured_output(),
            },
        ],
    )
    worker = Worker(test_database, fake_client)
    await _create_running_task(test_database, session_id)

    await worker.poll()

    task = await _get_task(test_database)
    assert task.status == "SUCCEEDED"
    assert task.devin_status == "suspended"


@pytest.mark.asyncio
async def test_recover_reclassifies_persisted_structured_output_without_api_call(
    test_database: Database,
) -> None:
    """Recovery reclassifies stored evidence without polling Devin."""
    session_id = "sess-recover-evidence"
    fake_client = FakeDevinClient([])
    worker = Worker(test_database, fake_client)
    await _create_running_task(test_database, session_id)

    async with test_database.get_session() as session:
        task = (await session.execute(select(RemediationTask))).scalar_one()
        task.status = "FAILED"
        task.structured_output = _success_structured_output()
        await session.commit()

    await worker.recover()

    task = await _get_task(test_database)
    assert task.status == "SUCCEEDED"
    assert task.verification_summary == "PASSED"
    assert task.error_code is None
    assert fake_client.calls == []

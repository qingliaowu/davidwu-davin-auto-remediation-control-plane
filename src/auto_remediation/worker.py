"""Background worker that dispatches and monitors Devin remediation sessions."""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from auto_remediation.config import settings
from auto_remediation.database import Database
from auto_remediation.devin_client import DevinClient, DevinClientError
from auto_remediation.models import RemediationTask
from auto_remediation.prompt import build_remediation_prompt, build_session_title, build_tags
from auto_remediation.verification import normalized_verification

logger = logging.getLogger(__name__)

_TERMINAL_STATUSES = {"SUCCEEDED", "FAILED"}
_WAITING_STATUSES = {"waiting_for_user", "waiting_for_approval"}
_POLL_TERMINAL_STATUSES = {"exit", "suspended", "completed"}
_IN_FLIGHT_STATUSES = {"DISPATCHING", "RUNNING", "WAITING_FOR_USER", "WAITING_FOR_APPROVAL"}


class Worker:
    """Polls the database, dispatches Devin sessions, and monitors their progress."""

    def __init__(self, database: Database, devin_client: DevinClient) -> None:
        self.db = database
        self.client = devin_client
        self.poll_interval = settings.poll_interval_seconds
        self.max_concurrent = settings.max_concurrent_tasks_per_repository
        self._task: asyncio.Task[None] | None = None
        self._stop = asyncio.Event()

    def _now(self) -> datetime:
        return datetime.now(UTC)

    async def start(self) -> None:
        """Recover state and begin the background polling loop."""
        await self.recover()
        self._task = asyncio.create_task(self._run())
        logger.info("Worker started")

    async def stop(self) -> None:
        """Signal the worker to stop and wait for the current cycle to finish."""
        self._stop.set()
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("Worker stopped")

    async def _run(self) -> None:
        while not self._stop.is_set():
            try:
                await self.poll()
            except Exception:
                logger.exception("Worker poll cycle failed")
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self.poll_interval)
            except asyncio.TimeoutError:
                pass

    async def recover(self) -> None:
        """Resume interrupted tasks after an application restart."""
        async with self.db.get_session() as session:
            non_terminal = await session.scalars(
                select(RemediationTask).where(
                    or_(
                        RemediationTask.status.notin_(_TERMINAL_STATUSES),
                        RemediationTask.structured_output.isnot(None),
                    ),
                ),
            )
            for task in non_terminal:
                if task.structured_output is not None and (
                    task.status in _TERMINAL_STATUSES
                    or self._has_completion_evidence(task, task.structured_output)
                ):
                    await self._finalize_task(
                        session,
                        task,
                        {"structured_output": task.structured_output},
                    )
                    continue
                if task.status == "DISPATCHING":
                    if task.devin_session_id:
                        task.status = "RUNNING"
                        logger.info("Recovered DISPATCHING task %s as RUNNING", task.task_id)
                    else:
                        task.status = "QUEUED"
                        logger.info(
                            "Recovered DISPATCHING task %s to QUEUED for redispatch", task.task_id
                        )
                elif task.devin_session_id and task.status == "QUEUED":
                    task.status = "RUNNING"
                    logger.info("Recovered QUEUED task %s with session as RUNNING", task.task_id)
            await session.commit()

    async def poll(self) -> None:
        """One worker cycle: poll active sessions, then dispatch eligible tasks."""
        async with self.db.get_session() as session:
            active = await session.scalars(
                select(RemediationTask).where(
                    RemediationTask.devin_session_id.isnot(None),
                    RemediationTask.status.notin_(_TERMINAL_STATUSES),
                ),
            )
            for task in active:
                await self._poll_task(session, task)
            await session.commit()

        async with self.db.get_session() as session:
            await self._dispatch_eligible(session)
            await session.commit()

    async def _poll_task(self, session: AsyncSession, task: RemediationTask) -> None:
        """Fetch the latest Devin session status and update the task."""
        if not task.devin_session_id:
            return

        try:
            devin_session = await self.client.get_session(task.devin_session_id)
        except DevinClientError as exc:
            logger.error("Failed to poll Devin session for task %s: %s", task.task_id, exc.message)
            task.error_code = "devin_poll_error"
            task.error_message = exc.message
            task.status = "FAILED"
            task.verification_status = "not_run"
            task.verification_summary = "FAILED"
            task.verification_warnings = []
            task.completed_at = self._now()
            task.duration_seconds = self._compute_duration(task)
            return

        task.devin_status = devin_session.get("status")
        task.devin_status_detail = devin_session.get("status_detail")
        task.devin_session_url = devin_session.get("url") or task.devin_session_url
        task.acus_consumed = devin_session.get("acus_consumed") or task.acus_consumed

        structured = devin_session.get("structured_output")
        if self._has_completion_evidence(task, structured):
            await self._finalize_task(session, task, devin_session)
            return

        devin_status = (devin_session.get("status") or "").lower()
        status_detail = (devin_session.get("status_detail") or "").lower()
        if status_detail in _WAITING_STATUSES:
            task.status = status_detail.upper()
            return

        if devin_status in _WAITING_STATUSES:
            task.status = devin_status.upper()
            return

        if devin_status in _POLL_TERMINAL_STATUSES:
            await self._finalize_task(session, task, devin_session)
            return

        # Nonterminal, active session.
        task.status = "RUNNING"

    async def _finalize_task(
        self,
        session: AsyncSession,
        task: RemediationTask,
        devin_session: dict[str, Any],
    ) -> None:
        """Classify a Devin session that has complete outcome evidence."""
        structured = devin_session.get("structured_output")
        task.structured_output = structured
        task.error_code = None
        task.error_message = None
        task.pull_request_url = None
        task.pull_request_number = None

        (
            final_status,
            verification_status,
            verification_summary,
            verification_warnings,
        ) = self._classify_final(task, structured)
        task.status = final_status
        task.verification_status = verification_status
        task.verification_summary = verification_summary
        task.verification_warnings = verification_warnings

        if structured:
            task.pull_request_url = self._real_pr_url(structured.get("pr_url"))
            pr_number = self._extract_pr_number(structured.get("pr_url"))
            if pr_number:
                task.pull_request_number = pr_number

        if task.completed_at is None:
            task.completed_at = self._now()
        if task.duration_seconds is None:
            task.duration_seconds = self._compute_duration(task)

        if final_status == "FAILED":
            if structured and structured.get("outcome") == "failed":
                task.error_code = "devin_failed"
                task.error_message = structured.get("summary") or "Devin reported failure"
            elif structured and not self._real_pr_url(structured.get("pr_url")):
                task.error_code = "no_pull_request"
                task.error_message = "No pull request was produced"
            elif verification_status == "failed":
                task.error_code = "verification_failed"
                task.error_message = "Required verification command failed"
            else:
                task.error_code = "completion_without_success"
                task.error_message = "Session completed without verifiable success"

    def _classify_final(
        self,
        task: RemediationTask,
        structured: dict[str, Any] | None,
    ) -> tuple[str, str, str, list[dict[str, Any]]]:
        """Determine the final task status from structured output and verification.

        A task is SUCCEEDED only when the structured output outcome is "success",
        a real pull request URL exists, and every required verification item passed.
        """
        if not structured:
            return "FAILED", "not_run", "FAILED", []

        outcome = structured.get("outcome")
        pr_url = self._real_pr_url(structured.get("pr_url"))
        verification = normalized_verification(task.issue_body, structured)
        required_items = [item for item in verification if item["required"]]
        supplemental_items = [item for item in verification if not item["required"]]

        required_failed = any(item.get("result") == "failed" for item in required_items)
        required_passed = all(item.get("result") == "passed" for item in required_items)
        verification_status = self._verification_status(required_items, bool(verification))
        warnings = [
            self._warning_item(item)
            for item in supplemental_items
            if item.get("result") != "passed"
        ]

        if outcome == "success" and pr_url and verification and required_passed:
            summary = "PASSED_WITH_WARNINGS" if warnings else "PASSED"
            return "SUCCEEDED", verification_status, summary, warnings

        if outcome == "failed" or required_failed:
            return "FAILED", "failed", "FAILED", warnings

        return "FAILED", verification_status, "FAILED", warnings

    @staticmethod
    def _verification_status(
        required_items: list[dict[str, Any]],
        has_verification: bool,
    ) -> str:
        if not has_verification:
            return "not_run"
        if any(item.get("result") == "failed" for item in required_items):
            return "failed"
        if all(item.get("result") == "passed" for item in required_items):
            return "passed"
        return "partial"

    @staticmethod
    def _warning_item(item: dict[str, Any]) -> dict[str, Any]:
        return {
            "command": item.get("command"),
            "exit_code": item.get("exit_code"),
            "result": item.get("result"),
            "notes": item.get("notes"),
        }

    @staticmethod
    def _real_pr_url(pr_url: Any) -> str | None:
        if isinstance(pr_url, str) and pr_url.strip():
            return pr_url.strip()
        return None

    @staticmethod
    def _has_completion_evidence(
        task: RemediationTask,
        structured: dict[str, Any] | None,
    ) -> bool:
        if not structured or not Worker._real_pr_url(structured.get("pr_url")):
            return False
        verification = normalized_verification(task.issue_body, structured)
        return bool(verification) and not any(
            item["required"] and item.get("result") == "not_run" for item in verification
        )

    def _extract_pr_number(self, pr_url: str | None) -> int | None:
        """Extract a pull request number from a GitHub PR URL."""
        if not pr_url:
            return None
        try:
            return int(pr_url.rstrip("/").rsplit("/", 1)[-1])
        except (ValueError, IndexError):
            return None

    def _compute_duration(self, task: RemediationTask) -> float | None:
        if task.session_started_at and task.completed_at:
            started = task.session_started_at
            completed = task.completed_at
            if started.tzinfo is None and completed.tzinfo is not None:
                started = started.replace(tzinfo=UTC)
            elif completed.tzinfo is None and started.tzinfo is not None:
                completed = completed.replace(tzinfo=UTC)
            return (completed - started).total_seconds()
        return None

    async def _dispatch_eligible(self, session: AsyncSession) -> None:
        """Claim and dispatch one QUEUED task per repository while honoring concurrency."""
        repo_result = await session.execute(select(RemediationTask.repository).distinct())
        repositories = repo_result.scalars().all()

        for repository in repositories:
            in_flight_count = await session.scalar(
                select(func.count(RemediationTask.id)).where(
                    RemediationTask.repository == repository,
                    RemediationTask.status.in_(_IN_FLIGHT_STATUSES),
                ),
            )
            if in_flight_count is None or in_flight_count >= self.max_concurrent:
                continue

            task = await session.scalar(
                select(RemediationTask)
                .where(
                    RemediationTask.repository == repository,
                    RemediationTask.status == "QUEUED",
                )
                .order_by(RemediationTask.id.asc()),
            )
            if task:
                await self._claim_and_dispatch(session, task)

    async def _claim_and_dispatch(self, session: AsyncSession, task: RemediationTask) -> None:
        """Create exactly one Devin session for a claimed QUEUED task."""
        now = self._now()
        task.status = "DISPATCHING"
        task.session_started_at = now
        task.queued_at = task.queued_at or now
        await session.flush()

        prompt = build_remediation_prompt(task)
        title = build_session_title(task)
        tags = build_tags(task)

        try:
            devin_session = await self.client.create_session(prompt, title, tags)
        except DevinClientError as exc:
            logger.error(
                "Failed to create Devin session for task %s: %s", task.task_id, exc.message
            )
            task.status = "FAILED"
            task.error_code = "devin_create_error"
            task.error_message = exc.message
            task.completed_at = self._now()
            task.duration_seconds = self._compute_duration(task)
            return

        task.devin_session_id = devin_session.get("session_id")
        task.devin_session_url = devin_session.get("url")
        task.devin_status = devin_session.get("status")
        task.status = "RUNNING"
        logger.info(
            "Dispatched task %s to Devin session %s",
            task.task_id,
            task.devin_session_id,
        )

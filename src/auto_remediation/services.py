"""Core webhook verification, eligibility, and remediation logic."""

from __future__ import annotations

import hashlib
import hmac
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from auto_remediation.config import settings
from auto_remediation.models import RemediationTask, WebhookDelivery

logger = logging.getLogger(__name__)

TASK_STATUSES = {
    "QUEUED",
    "DISPATCHING",
    "RUNNING",
    "WAITING_FOR_USER",
    "WAITING_FOR_APPROVAL",
    "SUCCEEDED",
    "FAILED",
}


@dataclass
class WebhookResult:
    """Result of handling a single GitHub webhook delivery."""

    status_code: int
    body: dict[str, Any]


def verify_signature(body: bytes, secret: str, signature: str | None) -> bool:
    """Verify a GitHub X-Hub-Signature-256 HMAC-SHA256 signature."""
    if not signature or not signature.startswith("sha256="):
        return False
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(signature[7:], expected)


def _now() -> datetime:
    return datetime.now(UTC)


def _classify_eligibility(
    event_name: str | None,
    payload: dict[str, Any],
    allowed_repository: str,
) -> tuple[bool, str | None]:
    """Return (eligible, ignored_reason) for a parsed GitHub webhook payload."""
    if event_name != "issues":
        return False, "event is not 'issues'"

    action = payload.get("action")
    if action != "labeled":
        return False, f"action '{action}' is not 'labeled'"

    repository = payload.get("repository", {})
    full_name = repository.get("full_name")
    if full_name != allowed_repository:
        return False, f"repository '{full_name}' is not allowed"

    issue = payload.get("issue", {})
    if issue.get("state") != "open":
        return False, "issue is not open"

    label = payload.get("label", {})
    if label.get("name") != "devin-fix":
        return False, f"label '{label.get('name')}' is not 'devin-fix'"

    return True, None


async def handle_github_event(
    session: AsyncSession,
    event_name: str | None,
    delivery_id: str | None,
    payload: dict[str, Any],
) -> WebhookResult:
    """Persist and route a verified GitHub event to a remediation task when eligible."""
    allowed_repository = settings.github_allowed_repository

    if not delivery_id:
        return WebhookResult(400, {"status": "ignored", "reason": "missing X-GitHub-Delivery"})

    existing = await session.scalar(
        select(WebhookDelivery).where(WebhookDelivery.github_delivery_id == delivery_id),
    )
    if existing:
        existing.attempt_count += 1
        await session.commit()
        return WebhookResult(
            200,
            {
                "status": "duplicate",
                "delivery_id": delivery_id,
                "attempt_count": existing.attempt_count,
                "outcome": existing.outcome,
            },
        )

    repository = payload.get("repository", {}).get("full_name")
    issue = payload.get("issue", {})
    issue_number = issue.get("number")

    eligible, ignored_reason = _classify_eligibility(event_name, payload, allowed_repository)

    delivery = WebhookDelivery(
        github_delivery_id=delivery_id,
        event_name=event_name,
        action=payload.get("action"),
        repository=repository,
        issue_number=issue_number,
        outcome="eligible" if eligible else "ignored",
        ignored_reason=ignored_reason,
        attempt_count=1,
        received_at=_now(),
    )
    session.add(delivery)
    await session.flush()

    task: RemediationTask | None = None
    if eligible:
        now = _now()
        task = RemediationTask(
            webhook_delivery_id=delivery.id,
            repository=repository,
            issue_number=issue_number,
            issue_title=issue.get("title"),
            issue_body=issue.get("body"),
            issue_url=issue.get("html_url") or issue.get("url"),
            target_branch=settings.github_target_branch,
            triggering_label="devin-fix",
            status="QUEUED",
            dry_run=settings.dry_run,
            received_at=now,
            queued_at=now,
        )
        session.add(task)

    await session.commit()

    if eligible and task:
        task_dict = task.to_dict()
        logger.info(
            "Created remediation task %s for %s#%s",
            task_dict["task_id"],
            repository,
            issue_number,
        )
        return WebhookResult(
            202,
            {
                "status": "eligible",
                "delivery_id": delivery_id,
                "task_id": task_dict["task_id"],
                "repository": repository,
                "issue_number": issue_number,
            },
        )

    logger.info("Ignored webhook %s: %s", delivery_id, ignored_reason)
    return WebhookResult(
        200,
        {
            "status": "ignored",
            "delivery_id": delivery_id,
            "reason": ignored_reason,
        },
    )


async def list_tasks(session: AsyncSession) -> list[RemediationTask]:
    """Return all remediation tasks ordered by most recent first."""
    result = await session.execute(select(RemediationTask).order_by(RemediationTask.id.desc()))
    return list(result.scalars().all())


async def get_task(session: AsyncSession, task_id: str) -> RemediationTask | None:
    """Fetch a single remediation task by its public task_id."""
    return await session.scalar(select(RemediationTask).where(RemediationTask.task_id == task_id))

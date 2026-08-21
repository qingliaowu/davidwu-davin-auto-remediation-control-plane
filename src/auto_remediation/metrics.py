"""Metrics aggregation for the control plane dashboard and API."""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from auto_remediation.models import RemediationTask, WebhookDelivery

_IN_FLIGHT_STATUSES = {"DISPATCHING", "RUNNING", "WAITING_FOR_USER", "WAITING_FOR_APPROVAL"}
_WAITING_STATUSES = {"WAITING_FOR_USER", "WAITING_FOR_APPROVAL"}


async def get_metrics(session: AsyncSession) -> dict[str, Any]:
    """Compute aggregate observability metrics from the database."""
    total_attempts = await session.scalar(
        select(func.coalesce(func.sum(WebhookDelivery.attempt_count), 0)),
    )
    unique_deliveries = await session.scalar(select(func.count(WebhookDelivery.id)))
    duplicate_attempts = (total_attempts or 0) - (unique_deliveries or 0)

    eligible_tasks = await session.scalar(select(func.count(RemediationTask.id)))
    ignored_events = await session.scalar(
        select(func.count(WebhookDelivery.id)).where(WebhookDelivery.outcome == "ignored"),
    )

    devin_sessions_created = await session.scalar(
        select(func.count(RemediationTask.id)).where(RemediationTask.devin_session_id.isnot(None)),
    )
    active_tasks = await session.scalar(
        select(func.count(RemediationTask.id)).where(
            RemediationTask.status.in_(_IN_FLIGHT_STATUSES)
        ),
    )
    waiting_tasks = await session.scalar(
        select(func.count(RemediationTask.id)).where(RemediationTask.status.in_(_WAITING_STATUSES)),
    )
    successful_tasks = await session.scalar(
        select(func.count(RemediationTask.id)).where(RemediationTask.status == "SUCCEEDED"),
    )
    failed_tasks = await session.scalar(
        select(func.count(RemediationTask.id)).where(RemediationTask.status == "FAILED"),
    )
    tasks_with_warnings = await session.scalar(
        select(func.count(RemediationTask.id)).where(
            RemediationTask.verification_summary == "PASSED_WITH_WARNINGS",
        ),
    )
    pull_requests_created = await session.scalar(
        select(func.count(RemediationTask.id)).where(RemediationTask.pull_request_url.isnot(None)),
    )

    avg_duration = await session.scalar(
        select(func.coalesce(func.avg(RemediationTask.duration_seconds), 0.0)).where(
            RemediationTask.status == "SUCCEEDED",
        ),
    )
    total_acus = await session.scalar(
        select(func.coalesce(func.sum(RemediationTask.acus_consumed), 0.0)),
    )

    completed = (successful_tasks or 0) + (failed_tasks or 0)
    success_rate = (successful_tasks / completed) if completed else 0.0

    return {
        "webhook_delivery_attempts": total_attempts or 0,
        "unique_webhook_deliveries": unique_deliveries or 0,
        "eligible_tasks": eligible_tasks or 0,
        "ignored_events": ignored_events or 0,
        "duplicate_attempts": duplicate_attempts,
        "devin_sessions_created": devin_sessions_created or 0,
        "active_tasks": active_tasks or 0,
        "waiting_tasks": waiting_tasks or 0,
        "successful_tasks": successful_tasks or 0,
        "failed_tasks": failed_tasks or 0,
        "tasks_with_warnings": tasks_with_warnings or 0,
        "pull_requests_created": pull_requests_created or 0,
        "success_rate": success_rate,
        "success_rate_percent": round(success_rate * 100, 1),
        "average_successful_task_duration_seconds": float(avg_duration or 0.0),
        "total_acus_consumed": float(total_acus or 0.0),
    }

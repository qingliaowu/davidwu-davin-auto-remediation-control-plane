"""SQLAlchemy ORM models for the control plane."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from auto_remediation.database import Base
from auto_remediation.verification import normalized_verification


class WebhookDelivery(Base):
    """Stores every GitHub webhook delivery for audit and idempotency."""

    __tablename__ = "webhook_deliveries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    github_delivery_id: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    event_name: Mapped[str | None] = mapped_column(String, nullable=True)
    action: Mapped[str | None] = mapped_column(String, nullable=True)
    repository: Mapped[str | None] = mapped_column(String, nullable=True)
    issue_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    outcome: Mapped[str] = mapped_column(String, default="unknown", nullable=False)
    ignored_reason: Mapped[str | None] = mapped_column(String, nullable=True)
    attempt_count: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
    )

    remediation_task: Mapped[RemediationTask | None] = relationship(
        "RemediationTask",
        back_populates="webhook_delivery",
        uselist=False,
    )

    def to_dict(self) -> dict[str, Any]:
        """Serialize the delivery to a JSON-safe dictionary."""
        return {
            "id": self.id,
            "github_delivery_id": self.github_delivery_id,
            "event_name": self.event_name,
            "action": self.action,
            "repository": self.repository,
            "issue_number": self.issue_number,
            "outcome": self.outcome,
            "ignored_reason": self.ignored_reason,
            "attempt_count": self.attempt_count,
            "received_at": self.received_at.isoformat() if self.received_at else None,
        }


class RemediationTask(Base):
    """Stores a durable remediation task created from an eligible webhook."""

    __tablename__ = "remediation_tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task_id: Mapped[str] = mapped_column(
        String,
        unique=True,
        default=lambda: str(uuid.uuid4()),
        nullable=False,
    )
    webhook_delivery_id: Mapped[int] = mapped_column(
        ForeignKey("webhook_deliveries.id"),
        nullable=False,
    )
    repository: Mapped[str] = mapped_column(String, nullable=False)
    issue_number: Mapped[int] = mapped_column(Integer, nullable=False)
    issue_title: Mapped[str | None] = mapped_column(String, nullable=True)
    issue_body: Mapped[str | None] = mapped_column(String, nullable=True)
    issue_url: Mapped[str | None] = mapped_column(String, nullable=True)
    target_branch: Mapped[str] = mapped_column(String, default="main", nullable=False)
    triggering_label: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, default="QUEUED", nullable=False)
    dry_run: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
    )
    queued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String, nullable=True)
    error_message: Mapped[str | None] = mapped_column(String, nullable=True)

    # Devin session and result fields
    devin_session_id: Mapped[str | None] = mapped_column(String, nullable=True)
    devin_session_url: Mapped[str | None] = mapped_column(String, nullable=True)
    devin_status: Mapped[str | None] = mapped_column(String, nullable=True)
    devin_status_detail: Mapped[str | None] = mapped_column(String, nullable=True)
    pull_request_url: Mapped[str | None] = mapped_column(String, nullable=True)
    pull_request_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    acus_consumed: Mapped[float | None] = mapped_column(Float, nullable=True)
    structured_output: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    verification_status: Mapped[str | None] = mapped_column(String, nullable=True)
    verification_summary: Mapped[str | None] = mapped_column(String, nullable=True)
    verification_warnings: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON, nullable=True)
    session_started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    duration_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)

    webhook_delivery: Mapped[WebhookDelivery] = relationship(
        "WebhookDelivery",
        back_populates="remediation_task",
    )

    @property
    def verification_items(self) -> list[dict[str, Any]]:
        """Return structured verification items with required classification."""
        return normalized_verification(self.issue_body, self.structured_output)

    def to_dict(self) -> dict[str, Any]:
        """Serialize the task to a JSON-safe dictionary."""
        return {
            "task_id": self.task_id,
            "webhook_delivery_id": self.webhook_delivery_id,
            "repository": self.repository,
            "issue_number": self.issue_number,
            "issue_title": self.issue_title,
            "issue_body": self.issue_body,
            "issue_url": self.issue_url,
            "target_branch": self.target_branch,
            "triggering_label": self.triggering_label,
            "status": self.status,
            "dry_run": self.dry_run,
            "received_at": self.received_at.isoformat() if self.received_at else None,
            "queued_at": self.queued_at.isoformat() if self.queued_at else None,
            "error_code": self.error_code,
            "error_message": self.error_message,
            "devin_session_id": self.devin_session_id,
            "devin_session_url": self.devin_session_url,
            "devin_status": self.devin_status,
            "devin_status_detail": self.devin_status_detail,
            "pull_request_url": self.pull_request_url,
            "pull_request_number": self.pull_request_number,
            "acus_consumed": self.acus_consumed,
            "structured_output": self.structured_output,
            "verification_status": self.verification_status,
            "verification_summary": self.verification_summary,
            "verification_warnings": self.verification_warnings,
            "session_started_at": self.session_started_at.isoformat()
            if self.session_started_at
            else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "duration_seconds": self.duration_seconds,
        }

"""Domain models for the control plane."""

from pydantic import BaseModel


class GitHubIssueEvent(BaseModel):
    """Minimal payload for a GitHub issues webhook event."""

    action: str
    issue: dict
    repository: dict


class RemediationRequest(BaseModel):
    """Internal request to start a Devin remediation session."""

    owner: str
    repo: str
    issue_number: int
    title: str
    body: str | None = None

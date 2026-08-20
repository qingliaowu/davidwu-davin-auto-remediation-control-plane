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


class RemediationResponse(BaseModel):
    """Result of dispatching a remediation request to Devin."""

    status: str
    owner: str
    repo: str
    issue_number: int
    title: str
    session_id: str | None = None
    session_url: str | None = None
    devin_status: str | None = None

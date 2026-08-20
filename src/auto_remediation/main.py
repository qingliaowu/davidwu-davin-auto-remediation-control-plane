"""HTTP entry point for GitHub webhooks and health checks."""

from fastapi import FastAPI

from auto_remediation.config import settings
from auto_remediation.control_plane import ControlPlane
from auto_remediation.models import GitHubIssueEvent, RemediationRequest

app = FastAPI(title="Auto Remediation Control Plane", version="0.1.0")
control_plane = ControlPlane()


@app.get("/health")
async def health() -> dict:
    """Health check endpoint."""
    return {"status": "ok"}


@app.post("/webhook/github")
async def github_webhook(payload: GitHubIssueEvent) -> dict:
    """Receive GitHub issue events and route approved issues to Devin."""
    if payload.action not in {"opened", "labeled", "edited"}:
        return {"status": "ignored", "action": payload.action}

    owner, repo = payload.repository.get("full_name", "/").split("/", 1)
    issue = payload.issue
    request = RemediationRequest(
        owner=owner,
        repo=repo,
        issue_number=issue.get("number", 0),
        title=issue.get("title", ""),
        body=issue.get("body"),
    )

    return await control_plane.handle_issue(request)


def start() -> None:
    """Run the control plane server."""
    import uvicorn

    uvicorn.run(app, host=settings.listen_host, port=settings.listen_port)


if __name__ == "__main__":
    start()

"""HTTP entry point for GitHub webhooks and health checks."""

import hashlib
import hmac
import logging

from fastapi import FastAPI, HTTPException, Request

from auto_remediation.config import settings
from auto_remediation.control_plane import ControlPlane
from auto_remediation.dashboard import router as dashboard_router
from auto_remediation.devin_client import DevinClientError
from auto_remediation.models import GitHubIssueEvent, RemediationRequest
from auto_remediation.store import store

logger = logging.getLogger(__name__)
app = FastAPI(title="Auto Remediation Control Plane", version="0.1.0")
app.include_router(dashboard_router)
control_plane = ControlPlane()


def _verify_github_signature(secret: str | None, body: bytes, signature: str | None) -> bool:
    """Verify a GitHub webhook HMAC-SHA256 signature."""
    if not secret:
        return True
    if not signature or not signature.startswith("sha256="):
        return False
    expected = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


@app.get("/health")
async def health() -> dict:
    """Health check endpoint."""
    return {"status": "ok"}


@app.post("/webhook/github")
async def github_webhook(request: Request) -> dict:
    """Receive GitHub issue events and route approved issues to Devin."""
    body = await request.body()
    signature = request.headers.get("x-hub-signature-256")

    if not _verify_github_signature(settings.webhook_secret, body, signature):
        raise HTTPException(status_code=401, detail="Invalid webhook signature")

    if not settings.webhook_secret:
        logger.warning("ARP_WEBHOOK_SECRET is not set; accepting unsigned webhooks")

    payload = GitHubIssueEvent.model_validate_json(body)
    if payload.action not in {"opened", "labeled", "edited"}:
        return {"status": "ignored", "action": payload.action}

    owner, repo = payload.repository.get("full_name", "/").split("/", 1)
    issue = payload.issue
    remediation = RemediationRequest(
        owner=owner,
        repo=repo,
        issue_number=issue.get("number", 0),
        title=issue.get("title", ""),
        body=issue.get("body"),
    )

    try:
        result = await control_plane.handle_issue(remediation)
    except DevinClientError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    await store.record(result.model_dump())
    return result.model_dump()


def start() -> None:
    """Run the control plane server."""
    import uvicorn

    uvicorn.run(app, host=settings.listen_host, port=settings.listen_port)


if __name__ == "__main__":
    start()

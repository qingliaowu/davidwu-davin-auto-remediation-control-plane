"""Core orchestration for the autonomous remediation control plane."""

from __future__ import annotations

import logging
from typing import Any

from auto_remediation.devin_client import DevinClient
from auto_remediation.models import RemediationRequest, RemediationResponse

logger = logging.getLogger(__name__)


class ControlPlane:
    """Routes approved issues to Devin sessions and verifies resulting PRs."""

    def __init__(self, devin_client: DevinClient | None = None) -> None:
        self._devin_client = devin_client

    @property
    def devin_client(self) -> DevinClient:
        if self._devin_client is None:
            self._devin_client = DevinClient()
        return self._devin_client

    @staticmethod
    def _build_prompt(request: RemediationRequest) -> str:
        """Build a prompt for Devin from a GitHub issue."""
        lines = [
            f"Fix the following issue in https://github.com/{request.owner}/{request.repo}.",
            "Create a pull request with your changes when you are done.",
            "",
            f"Issue #{request.issue_number}: {request.title}",
        ]
        if request.body:
            lines.extend(["", request.body])
        return "\n".join(lines)

    async def handle_issue(self, request: RemediationRequest) -> RemediationResponse:
        """Create a Devin session to remediate the approved issue."""
        logger.info(
            "Dispatching remediation to Devin: %s/%s#%d",
            request.owner,
            request.repo,
            request.issue_number,
        )

        prompt = self._build_prompt(request)
        session = await self.devin_client.create_session(
            prompt=prompt,
            title=f"Fix {request.owner}/{request.repo}#{request.issue_number}",
        )

        return RemediationResponse(
            status="dispatched",
            owner=request.owner,
            repo=request.repo,
            issue_number=request.issue_number,
            title=request.title,
            session_id=session.get("session_id"),
            session_url=session.get("url"),
            devin_status=session.get("status"),
        )

    async def verify_pull_request(self, owner: str, repo: str, pr_number: int) -> dict[str, Any]:
        """Stub for verifying a PR produced by Devin."""
        return {"status": "pending", "owner": owner, "repo": repo, "pr_number": pr_number}

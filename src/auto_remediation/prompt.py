"""Prompt construction for Devin remediation sessions."""

from __future__ import annotations

from auto_remediation.config import settings
from auto_remediation.models import RemediationTask


def build_remediation_prompt(task: RemediationTask) -> str:
    """Build a dynamic engineering prompt from a persisted remediation task."""
    issue_reference = f"#{task.issue_number}"
    if task.issue_url:
        issue_reference = f"{issue_reference} ({task.issue_url})"

    lines = [
        f"Work only in the repository {settings.devin_repo}.",
        f"Start from the latest state of the target branch: {task.target_branch}.",
        "",
        f"GitHub issue {issue_reference}: {task.issue_title or 'No title'}",
        "",
        (
            "Read the complete issue, inspect the relevant code, and understand the root cause "
            "and surrounding context before making any changes."
        ),
        (
            "Follow existing repository conventions, make the smallest correct change, "
            "and avoid unrelated formatting or refactoring."
        ),
        "",
        "Issue body:",
        task.issue_body or "(no body)",
        "",
        (
            "Run every verification command specified in the issue. If a verification command "
            "fails, investigate the failure honestly and fix the underlying problem. "
            "Do not weaken or remove checks, and do not claim success without evidence."
        ),
        (
            "In your structured verification output, mark every verification command specified "
            "in the GitHub issue as required: true. Any additional checks you choose to run "
            "yourself must be marked required: false."
        ),
        "Report any environmental blockers honestly.",
        "",
        "When the fix is ready:",
        f"1. Create a dedicated Git branch from {task.target_branch}.",
        "2. Commit the change with a clear message.",
        "3. Push the branch.",
        f"4. Create a pull request targeting {task.target_branch}.",
        f'5. Include "Closes #{task.issue_number}" in the pull request body.',
        "6. List all changed files in the pull request body.",
        "7. Include the exact verification commands you ran and their results.",
        "8. Do not merge the pull request.",
    ]
    return "\n".join(lines)


def build_session_title(task: RemediationTask) -> str:
    """Build a descriptive title for the Devin session."""
    return f"Fix {task.repository}#{task.issue_number}: {task.issue_title or 'remediation'}"


def build_tags(task: RemediationTask) -> list[str]:
    """Build dynamic tags for the Devin session."""
    return [
        "takehome",
        "workflow:autonomous-remediation",
        "source:github-webhook",
        f"repository:{task.repository}",
        f"issue:{task.issue_number}",
    ]

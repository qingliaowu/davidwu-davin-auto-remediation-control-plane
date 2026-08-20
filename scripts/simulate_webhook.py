#!/usr/bin/env python3
"""Sign and send a realistic GitHub issues.labeled webhook to the control plane."""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import sys
import uuid

import httpx
from dotenv import load_dotenv


def build_payload(
    repository: str,
    issue_number: int,
    issue_title: str,
    label: str = "devin-fix",
) -> dict[str, object]:
    """Build a realistic GitHub issues.labeled payload."""
    owner, repo = repository.split("/", 1)
    return {
        "action": "labeled",
        "issue": {
            "number": issue_number,
            "title": issue_title,
            "body": (
                f"Issue #{issue_number}: {issue_title}\n\n"
                "This is a simulated issue for local testing."
            ),
            "state": "open",
            "html_url": f"https://github.com/{repository}/issues/{issue_number}",
        },
        "repository": {
            "id": 123456789,
            "full_name": repository,
            "owner": {"login": owner},
            "name": repo,
            "html_url": f"https://github.com/{repository}",
        },
        "label": {"name": label, "color": "d876e3"},
        "sender": {"login": "octocat", "id": 1},
    }


def sign_payload(body: bytes, secret: str) -> str:
    """Compute the X-Hub-Signature-256 header for the exact body bytes."""
    signature = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return f"sha256={signature}"


def send_payload(
    base_url: str,
    secret: str,
    payload: dict[str, object],
    delivery_id: str,
) -> httpx.Response:
    """Send a single signed webhook request."""
    body = json.dumps(payload, separators=(",", ":")).encode()
    headers = {
        "X-GitHub-Event": "issues",
        "X-GitHub-Delivery": delivery_id,
        "X-Hub-Signature-256": sign_payload(body, secret),
        "Content-Type": "application/json",
        "User-Agent": "GitHub-Hookshot/test",
    }
    return httpx.post(f"{base_url}/webhooks/github", content=body, headers=headers)


def run(
    repository: str,
    issue_number: int,
    issue_title: str,
    label: str,
    secret: str,
    base_url: str,
    duplicate: bool,
) -> int:
    """Run the simulator and return the process exit code."""
    payload = build_payload(repository, issue_number, issue_title, label)
    delivery_id = str(uuid.uuid4())

    labels = "duplicate" if duplicate else "single"
    print(f"Sending {labels} signed webhook(s) to {base_url}/webhooks/github")
    print(f"Repository: {repository}")
    print(f"Issue: #{issue_number} {issue_title}")
    print(f"Delivery ID: {delivery_id}")

    attempts = 2 if duplicate else 1
    for attempt in range(1, attempts + 1):
        try:
            response = send_payload(base_url, secret, payload, delivery_id)
            print(f"Attempt {attempt}: {response.status_code} {response.text}")
        except httpx.RequestError as exc:
            print(f"Attempt {attempt}: request failed — {exc}", file=sys.stderr)
            return 1

    return 0


def main(argv: list[str] | None = None) -> int:
    """Parse arguments and run the simulator."""
    load_dotenv()

    parser = argparse.ArgumentParser(
        description="Send a signed GitHub issues.labeled webhook to the control plane.",
    )
    parser.add_argument("--issue-number", type=int, required=True)
    parser.add_argument("--issue-title", type=str, required=True)
    parser.add_argument("--label", type=str, default="devin-fix")
    parser.add_argument("--repository", type=str, default=os.getenv("GITHUB_ALLOWED_REPOSITORY"))
    parser.add_argument("--secret", type=str, default=os.getenv("GITHUB_WEBHOOK_SECRET"))
    parser.add_argument("--host", type=str, default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--duplicate", action="store_true")
    args = parser.parse_args(argv)

    if not args.repository:
        print(
            "GITHUB_ALLOWED_REPOSITORY is required. Set it in .env or pass --repository.",
            file=sys.stderr,
        )
        return 1
    if not args.secret:
        print(
            "GITHUB_WEBHOOK_SECRET is required. Set it in .env or pass --secret.",
            file=sys.stderr,
        )
        return 1

    base_url = f"http://{args.host}:{args.port}"
    return run(
        repository=args.repository,
        issue_number=args.issue_number,
        issue_title=args.issue_title,
        label=args.label,
        secret=args.secret,
        base_url=base_url,
        duplicate=args.duplicate,
    )


if __name__ == "__main__":
    raise SystemExit(main())

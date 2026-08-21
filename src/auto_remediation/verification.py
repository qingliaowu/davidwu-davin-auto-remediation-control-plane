"""Verification item classification helpers."""

from __future__ import annotations

from typing import Any


def is_required_verification(issue_body: str | None, item: dict[str, Any]) -> bool:
    """Determine whether a verification item is required for the task."""
    explicit_required = item.get("required")
    if isinstance(explicit_required, bool):
        return explicit_required

    command = item.get("command")
    if not isinstance(command, str) or not command.strip():
        return False
    return command.casefold() in (issue_body or "").casefold()


def normalized_verification(
    issue_body: str | None,
    structured_output: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    """Return verification items with their required classification."""
    if not structured_output:
        return []
    verification = structured_output.get("verification") or []
    if not isinstance(verification, list):
        return []

    items = [item for item in verification if isinstance(item, dict)]
    has_explicit_required = any("required" in item for item in items)
    normalized: list[dict[str, Any]] = []
    for item in items:
        normalized.append(
            {
                **item,
                "required": is_required_verification(issue_body, item),
            },
        )

    if (
        normalized
        and not has_explicit_required
        and not any(item["required"] for item in normalized)
    ):
        normalized = [
            {
                **item,
                "required": True,
            }
            for item in normalized
        ]
    return normalized

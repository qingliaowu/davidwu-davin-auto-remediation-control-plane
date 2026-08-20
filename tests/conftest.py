"""Shared test fixtures."""

from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient

from auto_remediation.database import Database
from auto_remediation.main import app


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch, tmp_path: pytest.TempPathFactory) -> TestClient:
    """Provide a TestClient backed by a temporary SQLite database."""
    test_db = Database(f"sqlite+aiosqlite:///{tmp_path}/test.db")

    # Both the lifespan handler and the dependency factory read a module-level db.
    monkeypatch.setattr("auto_remediation.database.db", test_db)
    monkeypatch.setattr("auto_remediation.main.db", test_db)

    monkeypatch.setattr("auto_remediation.config.settings.github_webhook_secret", "supersecret")
    monkeypatch.setattr("auto_remediation.config.settings.github_allowed_repository", "owner/repo")

    # Create tables before the app starts so non-lifespan test clients also work.
    asyncio.run(test_db.setup())

    with TestClient(app) as test_client:
        yield test_client

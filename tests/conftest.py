"""Shared test fixtures."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient

from auto_remediation.database import Database
from auto_remediation.devin_client import DevinClient
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


@pytest_asyncio.fixture
async def test_database(tmp_path: pytest.TempPathFactory) -> AsyncGenerator[Database, None]:
    """Provide an isolated in-memory async database."""
    db = Database(f"sqlite+aiosqlite:///{tmp_path}/test.db")
    await db.setup()
    try:
        yield db
    finally:
        await db.engine.dispose()


@pytest_asyncio.fixture
async def db_session(test_database: Database) -> AsyncGenerator:
    """Provide an async SQLAlchemy session."""
    async with test_database.get_session() as session:
        yield session


@pytest.fixture
def devin_client() -> DevinClient:
    """Provide a Devin client configured for unit tests."""
    return DevinClient(
        base_url="https://api.devin.ai",
        api_key="test-api-key",
        org_id="test-org",
        dry_run=False,
    )

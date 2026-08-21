"""Tests for additive database schema reconciliation."""

from __future__ import annotations

from sqlalchemy import inspect, text

from auto_remediation.database import Database


async def test_setup_adds_columns_missing_from_existing_tasks_table(tmp_path) -> None:
    """Database setup adds newly introduced task columns without dropping data."""
    database = Database(f"sqlite+aiosqlite:///{tmp_path}/migration.db")
    await database.setup()

    async with database.engine.begin() as connection:
        await connection.execute(
            text("ALTER TABLE remediation_tasks DROP COLUMN verification_summary"),
        )
        await connection.execute(
            text("ALTER TABLE remediation_tasks DROP COLUMN verification_warnings"),
        )

    await database.setup()

    async with database.engine.begin() as connection:
        columns = await connection.run_sync(
            lambda sync_connection: {
                column["name"]
                for column in inspect(sync_connection).get_columns("remediation_tasks")
            },
        )
    assert "verification_summary" in columns
    assert "verification_warnings" in columns
    await database.engine.dispose()

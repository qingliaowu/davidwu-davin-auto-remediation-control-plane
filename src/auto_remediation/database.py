"""Async SQLAlchemy database setup."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from auto_remediation.config import settings


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""


class Database:
    """Manages the async engine and session factory."""

    def __init__(self, database_url: str) -> None:
        self.engine = create_async_engine(database_url)
        self.session_maker: async_sessionmaker[AsyncSession] = async_sessionmaker(
            self.engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )

    async def setup(self) -> None:
        """Create all tables."""
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            await conn.run_sync(self._add_missing_columns)

    @staticmethod
    def _add_missing_columns(connection: Connection) -> None:
        """Add model columns missing from tables created by an older release."""
        inspector = inspect(connection)
        preparer = connection.dialect.identifier_preparer
        existing_tables = set(inspector.get_table_names())

        for table in Base.metadata.sorted_tables:
            if table.name not in existing_tables:
                continue
            existing_columns = {column["name"] for column in inspector.get_columns(table.name)}
            for column in table.columns:
                if column.name in existing_columns:
                    continue

                table_name = preparer.quote(table.name)
                column_sql = (
                    f"{preparer.quote(column.name)} "
                    f"{column.type.compile(dialect=connection.dialect)}"
                )
                if not column.nullable:
                    column_sql += " NOT NULL"
                connection.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {column_sql}"))

    @asynccontextmanager
    async def get_session(self) -> AsyncGenerator[AsyncSession, None]:
        """Yield an async database session."""
        async with self.session_maker() as session:
            yield session


# Global database instance used by the application and tests.
db = Database(settings.database_url)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency that yields an async database session."""
    async with db.get_session() as session:
        yield session

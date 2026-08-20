"""Async SQLAlchemy database setup."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

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

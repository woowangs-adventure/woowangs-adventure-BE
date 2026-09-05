from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Protocol

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


class DatabaseConnection(Protocol):
    async def ping(self) -> bool: ...

    async def close(self) -> None: ...

    def session(self) -> AsyncIterator[AsyncSession]: ...


class Database:
    def __init__(self, url: str) -> None:
        self._engine: AsyncEngine = create_async_engine(
            url,
            pool_pre_ping=True,
            pool_recycle=1800,
        )
        self._session_factory = async_sessionmaker(
            self._engine,
            expire_on_commit=False,
        )

    async def ping(self) -> bool:
        try:
            async with self._engine.connect() as connection:
                await connection.execute(text("SELECT 1 FROM robots LIMIT 1"))
            return True
        except (OSError, SQLAlchemyError):
            return False

    async def close(self) -> None:
        await self._engine.dispose()

    @asynccontextmanager
    async def session(self) -> AsyncIterator[AsyncSession]:
        async with self._session_factory() as session:
            yield session

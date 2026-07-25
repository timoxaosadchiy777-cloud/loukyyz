"""Фасад доступа к БД: движок, фабрика async-сессий и хелперы (для DI)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from database.engine import build_engine
from models.base import Base


class Database:
    """Владеет движком и sessionmaker; выдаёт транзакционные сессии."""

    def __init__(self, url: str, *, echo: bool = False, sqlite_path: Path | None = None) -> None:
        if sqlite_path is not None:
            sqlite_path.parent.mkdir(parents=True, exist_ok=True)
        self._engine = build_engine(url, echo=echo)
        self._sessionmaker: async_sessionmaker[AsyncSession] = async_sessionmaker(
            self._engine,
            expire_on_commit=False,
            class_=AsyncSession,
        )

    @property
    def sessionmaker(self) -> async_sessionmaker[AsyncSession]:
        return self._sessionmaker

    @asynccontextmanager
    async def session(self) -> AsyncIterator[AsyncSession]:
        """Транзакционная сессия: commit при успехе, rollback при исключении."""
        async with self._sessionmaker() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    async def create_all(self) -> None:
        """Создаёт схему из метаданных (для тестов; в проде — Alembic)."""
        async with self._engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    async def dispose(self) -> None:
        await self._engine.dispose()

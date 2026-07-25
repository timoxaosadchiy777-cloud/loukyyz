"""Обобщённый репозиторий (Repository Pattern) поверх async-сессии."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Generic, TypeVar

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.base import Base

ModelT = TypeVar("ModelT", bound=Base)


class BaseRepository(Generic[ModelT]):
    """Базовые CRUD-операции. Подклассы задают атрибут `model`."""

    model: type[ModelT]

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, obj: ModelT) -> ModelT:
        self._session.add(obj)
        await self._session.flush()
        return obj

    async def get(self, obj_id: int) -> ModelT | None:
        return await self._session.get(self.model, obj_id)

    async def list(self, *, limit: int = 100, offset: int = 0) -> Sequence[ModelT]:
        result = await self._session.execute(
            select(self.model).limit(limit).offset(offset)
        )
        return result.scalars().all()

    async def delete(self, obj: ModelT) -> None:
        await self._session.delete(obj)
        await self._session.flush()

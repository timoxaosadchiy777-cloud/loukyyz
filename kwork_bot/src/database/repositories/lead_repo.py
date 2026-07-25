"""Репозиторий заказов: дедупликация, создание, смена статуса и отклика."""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import select

from database.repositories.base import BaseRepository
from models.lead import Lead
from schemas.lead import LeadCreate


class LeadRepository(BaseRepository[Lead]):
    """Доступ к таблице `leads`."""

    model = Lead

    async def get_by_external(self, source: str, external_id: str) -> Lead | None:
        result = await self._session.execute(
            select(Lead).where(
                Lead.source == source,
                Lead.external_id == external_id,
            )
        )
        return result.scalar_one_or_none()

    async def exists(self, source: str, external_id: str) -> bool:
        result = await self._session.execute(
            select(Lead.id).where(
                Lead.source == source,
                Lead.external_id == external_id,
            ).limit(1)
        )
        return result.first() is not None

    async def create(
        self,
        data: LeadCreate,
        *,
        status: str = "new",
        response_text: str | None = None,
    ) -> Lead:
        lead = Lead(
            source=data.source,
            external_id=data.external_id,
            title=data.title,
            url=data.url,
            description=data.description,
            budget_raw=data.budget_raw,
            budget_value=data.budget_value,
            status=status,
            response_text=response_text,
        )
        return await self.add(lead)

    async def set_status(self, lead_id: int, status: str) -> None:
        lead = await self.get(lead_id)
        if lead is not None:
            lead.status = status
            await self._session.flush()

    async def set_response(self, lead_id: int, response_text: str) -> None:
        lead = await self.get(lead_id)
        if lead is not None:
            lead.response_text = response_text
            await self._session.flush()

    async def list_by_status(self, status: str, *, limit: int = 100) -> Sequence[Lead]:
        result = await self._session.execute(
            select(Lead).where(Lead.status == status).order_by(Lead.id.desc()).limit(limit)
        )
        return result.scalars().all()

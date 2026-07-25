"""Репозиторий доставок: антидубли и статусы отправки в Telegram."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select

from database.repositories.base import BaseRepository
from models.delivery import Delivery


class DeliveryRepository(BaseRepository[Delivery]):
    """Доступ к таблице `deliveries`."""

    model = Delivery

    async def exists(self, lead_id: int, chat_id: int) -> bool:
        result = await self._session.execute(
            select(Delivery.id).where(
                Delivery.lead_id == lead_id,
                Delivery.chat_id == chat_id,
            ).limit(1)
        )
        return result.first() is not None

    async def create(self, lead_id: int, chat_id: int, *, status: str = "queued") -> Delivery:
        delivery = Delivery(lead_id=lead_id, chat_id=chat_id, status=status)
        return await self.add(delivery)

    async def mark_sent(self, delivery_id: int, message_id: int) -> None:
        delivery = await self.get(delivery_id)
        if delivery is not None:
            delivery.status = "sent"
            delivery.message_id = message_id
            delivery.sent_at = datetime.now(timezone.utc)
            await self._session.flush()

    async def mark_failed(self, delivery_id: int) -> None:
        delivery = await self.get(delivery_id)
        if delivery is not None:
            delivery.status = "failed"
            await self._session.flush()

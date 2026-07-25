"""Сервис доставки карточек в Telegram.

- Очередь отправки на `asyncio.Queue` + фоновый воркер.
- Антидубли: факт доставки (lead_id, chat_id) фиксируется в БД (UNIQUE).
- Retry отправки только для временных ошибок Telegram (flood/сеть/5xx).
- Проваленные доставки логируются и помечаются в БД статусом `failed`.

Реализует протокол `services.interfaces.LeadDeliverer` (метод `enqueue`).
"""

from __future__ import annotations

import asyncio
import logging

from aiogram import Bot
from aiogram.exceptions import (
    TelegramNetworkError,
    TelegramRetryAfter,
    TelegramServerError,
)
from aiogram.types import LinkPreviewOptions

from database.repositories.delivery_repo import DeliveryRepository
from database.session import Database
from schemas.lead import LeadRead
from telegram.cards import render_card
from telegram.keyboards import lead_keyboard
from utils.retry import retry_async

log = logging.getLogger(__name__)

_NO_PREVIEW = LinkPreviewOptions(is_disabled=True)


def _is_transient(exc: BaseException) -> bool:
    return isinstance(exc, (TelegramRetryAfter, TelegramNetworkError, TelegramServerError))


def _delay_for(exc: BaseException, _attempt: int) -> float | None:
    # Telegram flood-control сообщает точную задержку в retry_after.
    if isinstance(exc, TelegramRetryAfter):
        return float(exc.retry_after)
    return None


class DeliveryService:
    """Очередь и отправка карточек владельцу с антидублями и ретраями."""

    def __init__(
        self,
        *,
        bot: Bot,
        database: Database,
        owner_id: int,
        retry_attempts: int = 3,
        retry_base_delay: float = 2.0,
        retry_max_delay: float = 30.0,
    ) -> None:
        self._bot = bot
        self._database = database
        self._owner_id = owner_id
        self._retry_attempts = retry_attempts
        self._retry_base_delay = retry_base_delay
        self._retry_max_delay = retry_max_delay
        self._queue: asyncio.Queue[tuple[LeadRead, str | None]] = asyncio.Queue()

    async def enqueue(self, lead: LeadRead, response: str | None) -> None:
        """Ставит карточку в очередь отправки (реализация LeadDeliverer)."""
        await self._queue.put((lead, response))

    async def worker(self) -> None:
        """Бесконечный воркер очереди доставки (запускается в TaskGroup)."""
        log.info("DeliveryService: воркер запущен")
        while True:
            lead, response = await self._queue.get()
            try:
                await self._deliver(lead, response)
            except Exception:  # noqa: BLE001 — воркер не должен падать
                log.exception("DeliveryService: непредвиденная ошибка доставки заказа %s", lead.id)
            finally:
                self._queue.task_done()

    async def _deliver(self, lead: LeadRead, response: str | None) -> None:
        chat_id = self._owner_id
        if not chat_id:
            log.warning("OWNER_ID не задан — карточка %s не отправлена", lead.id)
            return

        # Антидубль + регистрация доставки.
        async with self._database.session() as session:
            repo = DeliveryRepository(session)
            if await repo.exists(lead.id, chat_id):
                log.info("Заказ %s уже доставлялся в чат %s — пропуск", lead.id, chat_id)
                return
            delivery = await repo.create(lead.id, chat_id)
            delivery_id = delivery.id

        text = render_card(lead, response)
        markup = lead_keyboard(lead.id, lead.url)

        try:
            message = await retry_async(
                lambda: self._bot.send_message(
                    chat_id,
                    text,
                    reply_markup=markup,
                    link_preview_options=_NO_PREVIEW,
                ),
                attempts=self._retry_attempts,
                base_delay=self._retry_base_delay,
                max_delay=self._retry_max_delay,
                exceptions=(Exception,),
                retry_if=_is_transient,
                delay_for=_delay_for,
                label=f"tg-send:{lead.id}",
            )
        except Exception as exc:  # noqa: BLE001 — фиксируем провал, не роняем воркер
            async with self._database.session() as session:
                await DeliveryRepository(session).mark_failed(delivery_id)
            log.error("DeliveryService: доставка заказа %s не удалась: %s", lead.id, exc)
            return

        async with self._database.session() as session:
            await DeliveryRepository(session).mark_sent(delivery_id, message.message_id)
        log.info("Заказ %s доставлен (message_id=%s)", lead.id, message.message_id)

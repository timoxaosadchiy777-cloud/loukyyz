"""Мониторинг Telegram-чатов по ключевым словам через Telethon."""

from __future__ import annotations

import asyncio
import logging

from telethon import TelegramClient, events

from config import Settings
from core.models import Order
from parsers.base import BaseParser

log = logging.getLogger(__name__)


class TelegramParser(BaseParser):
    """Слушает новые сообщения в заданных чатах и фильтрует по ключевым словам."""

    name = "telegram"

    def __init__(self, queue: "asyncio.Queue[Order]", settings: Settings) -> None:
        super().__init__(queue)
        self._settings = settings
        self._client = TelegramClient(
            settings.tg_session,
            settings.tg_api_id,
            settings.tg_api_hash,
        )

    async def run(self) -> None:
        if not self._settings.telegram_ready:
            log.warning("Telegram-парсер выключен: не заданы TG_API_ID / TG_API_HASH")
            return

        chats = self._settings.tg_chats or None  # None => все диалоги
        keywords = [k.lower() for k in self._settings.tg_keywords]

        self._client.add_event_handler(
            self._make_handler(keywords),
            events.NewMessage(chats=chats),
        )

        await self._client.start(phone=self._settings.tg_phone or None)
        log.info(
            "Telegram-парсер запущен (чатов: %s, ключевых слов: %s)",
            len(self._settings.tg_chats) or "все",
            len(keywords) or "нет фильтра",
        )
        await self._client.run_until_disconnected()

    def _make_handler(self, keywords: list[str]):
        async def handler(event: events.NewMessage.Event) -> None:
            text = (event.raw_text or "").strip()
            if not text:
                return
            if keywords and not any(k in text.lower() for k in keywords):
                return

            title = text.split("\n", 1)[0][:120] or "Заказ из Telegram"
            order = Order(
                source=self.name,
                external_id=f"{event.chat_id}:{event.id}",
                title=title,
                url=self._build_url(event),
                description=text,
            )
            await self.emit(order)

        return handler

    @staticmethod
    def _build_url(event: events.NewMessage.Event) -> str:
        chat = event.chat
        username = getattr(chat, "username", None)
        if username:
            return f"https://t.me/{username}/{event.id}"
        # Приватные супергруппы: t.me/c/<internal_id>/<msg_id>
        internal = str(event.chat_id).replace("-100", "")
        return f"https://t.me/c/{internal}/{event.id}"

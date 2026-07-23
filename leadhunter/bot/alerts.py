"""Алёрты владельцу об ошибках парсеров и ИИ (с антиспам-троттлингом)."""

from __future__ import annotations

import logging
import time

from aiogram import Bot

log = logging.getLogger(__name__)


class Alerter:
    """Шлёт технические уведомления владельцу, не чаще раза в ``cooldown`` секунд на ключ."""

    def __init__(self, bot: Bot, owner_id: int, cooldown: int = 300) -> None:
        self._bot = bot
        self._owner_id = owner_id
        self._cooldown = cooldown
        self._last_sent: dict[str, float] = {}

    async def alert(self, text: str, key: str | None = None) -> None:
        """Отправляет алёрт. ``key`` группирует однотипные ошибки для троттлинга."""
        if not self._owner_id:
            log.warning("ALERT (OWNER_ID не задан): %s", text)
            return

        throttle_key = key or text
        now = time.monotonic()
        last = self._last_sent.get(throttle_key, 0.0)
        if now - last < self._cooldown:
            log.debug("Алёрт %r подавлен троттлингом", throttle_key)
            return

        self._last_sent[throttle_key] = now
        try:
            await self._bot.send_message(self._owner_id, f"⚠️ {text}", parse_mode=None)
        except Exception:
            log.exception("Не удалось доставить алёрт владельцу")

"""Middleware антидубля повторных нажатий инлайн-кнопок."""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, TelegramObject


class DedupMiddleware(BaseMiddleware):
    """Гасит повторные одинаковые callback-нажатия в пределах TTL."""

    def __init__(self, ttl: float = 2.0) -> None:
        self._ttl = ttl
        self._seen: dict[tuple[int, str], float] = {}

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if isinstance(event, CallbackQuery) and event.data:
            now = time.monotonic()
            self._purge(now)
            key = (event.from_user.id, event.data)
            if key in self._seen:
                await event.answer()  # тихо подтверждаем, повторно не обрабатываем
                return None
            self._seen[key] = now + self._ttl
        return await handler(event, data)

    def _purge(self, now: float) -> None:
        expired = [key for key, exp in self._seen.items() if exp <= now]
        for key in expired:
            self._seen.pop(key, None)

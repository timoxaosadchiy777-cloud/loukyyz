"""Middleware ограничения частоты действий пользователя."""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, TelegramObject, User


class RateLimitMiddleware(BaseMiddleware):
    """Отсекает слишком частые действия одного пользователя (минимальный интервал)."""

    def __init__(self, interval: float = 0.7) -> None:
        self._interval = interval
        self._last_seen: dict[int, float] = {}

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user: User | None = data.get("event_from_user")
        if user is not None:
            now = time.monotonic()
            last = self._last_seen.get(user.id, 0.0)
            if now - last < self._interval:
                if isinstance(event, CallbackQuery):
                    await event.answer("Слишком часто, подождите секунду")
                return None
            self._last_seen[user.id] = now
        return await handler(event, data)

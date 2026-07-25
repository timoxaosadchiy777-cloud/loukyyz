"""Middleware проверки лицензии перед обработкой любого апдейта."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject

from security.license_service import LicenseVerifier

log = logging.getLogger(__name__)


class LicenseMiddleware(BaseMiddleware):
    """Пропускает апдейт дальше только при действующей лицензии."""

    def __init__(self, verifier: LicenseVerifier) -> None:
        self._verifier = verifier

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        status = self._verifier.verify()
        if status.valid:
            return await handler(event, data)

        log.warning("Лицензия недействительна: %s", status.reason)
        if isinstance(event, Message):
            await event.answer(f"❌ Лицензия недействительна: {status.reason}")
        elif isinstance(event, CallbackQuery):
            await event.answer("❌ Лицензия недействительна", show_alert=True)
        return None

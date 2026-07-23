"""Базовый класс парсера.

Парсеры складывают найденные заказы в общую asyncio.Queue, откуда их забирает
пайплайн обработки. Такой подход развязывает источники и обработку.
"""

from __future__ import annotations

import abc
import asyncio
import logging
from typing import TYPE_CHECKING

from core.models import Order

if TYPE_CHECKING:
    from bot.alerts import Alerter

log = logging.getLogger(__name__)


class BaseParser(abc.ABC):
    """Общий контракт для всех источников заказов."""

    name: str = "base"

    def __init__(
        self,
        queue: "asyncio.Queue[Order]",
        alerter: "Alerter | None" = None,
    ) -> None:
        self._queue = queue
        self._alerter = alerter

    async def emit(self, order: Order) -> None:
        """Публикует заказ в очередь обработки."""
        await self._queue.put(order)
        log.debug("[%s] emit %s", self.name, order.dedup_key)

    async def alert(self, text: str, key: str | None = None) -> None:
        """Отправляет технический алёрт владельцу (если алёртер подключён)."""
        if self._alerter is not None:
            await self._alerter.alert(text, key=key)

    async def run_safe(self) -> None:
        """Запускает парсер, гася любые исключения (чтобы не ронять gather)."""
        try:
            await self.run()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.exception("[%s] парсер аварийно остановлен", self.name)
            await self.alert(
                f"Парсер «{self.name}» аварийно остановлен: {exc}",
                key=f"parser-crash:{self.name}",
            )

    @abc.abstractmethod
    async def run(self) -> None:
        """Основной цикл парсера."""
        raise NotImplementedError

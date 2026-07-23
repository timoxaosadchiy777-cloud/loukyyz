"""Базовый класс парсера.

Парсеры складывают найденные заказы в общую asyncio.Queue, откуда их забирает
пайплайн обработки. Такой подход развязывает источники и обработку.
"""

from __future__ import annotations

import abc
import asyncio
import logging

from core.models import Order

log = logging.getLogger(__name__)


class BaseParser(abc.ABC):
    """Общий контракт для всех источников заказов."""

    name: str = "base"

    def __init__(self, queue: "asyncio.Queue[Order]") -> None:
        self._queue = queue

    async def emit(self, order: Order) -> None:
        """Публикует заказ в очередь обработки."""
        await self._queue.put(order)
        log.debug("[%s] emit %s", self.name, order.dedup_key)

    async def run_safe(self) -> None:
        """Запускает парсер, гася любые исключения (чтобы не ронять gather)."""
        try:
            await self.run()
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("[%s] парсер аварийно остановлен", self.name)

    @abc.abstractmethod
    async def run(self) -> None:
        """Основной цикл парсера."""
        raise NotImplementedError

"""Базовый класс парсера.

Парсеры складывают найденные заказы в общую asyncio.Queue, откуда их забирает
пайплайн обработки. Такой подход развязывает источники и обработку.
"""

from __future__ import annotations

import abc
import asyncio
import logging
from collections import OrderedDict
from typing import TYPE_CHECKING

from core.models import Order

if TYPE_CHECKING:
    from bot.alerts import Alerter

log = logging.getLogger(__name__)

# Сколько ключей лидов держим в памяти на парсер. Одна страница биржи — это
# десятки записей, так что окна в несколько тысяч хватает с большим запасом.
SEEN_LIMIT = 5000


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
        # Ключи уже отданных за эту сессию лидов — чтобы не заваливать очередь
        # одними и теми же записями на каждом опросе фида (дедуп по БД идёт дальше,
        # но он молчаливый и всё равно гоняет их через очередь впустую).
        #
        # Набор ОГРАНИЧЕН: раньше это было обычное множество, которое росло всё
        # время работы процесса. На VPS с аптаймом в месяцы это медленная утечка
        # памяти. Держим окно последних ключей — старые лиды всё равно отсеются
        # дедупом по базе.
        self._seen: OrderedDict[str, None] = OrderedDict()

    async def emit(self, order: Order) -> bool:
        """Публикует заказ в очередь обработки.

        Returns:
            ``True`` — заказ поставлен в очередь; ``False`` — уже отдавался в этой
            сессии и повторно не публикуется.
        """
        if order.dedup_key in self._seen:
            # Двигаем в конец: активно повторяющиеся лиды не вытесняются.
            self._seen.move_to_end(order.dedup_key)
            return False

        self._seen[order.dedup_key] = None
        while len(self._seen) > SEEN_LIMIT:
            self._seen.popitem(last=False)

        await self._queue.put(order)
        log.debug("[%s] emit %s", self.name, order.dedup_key)
        return True

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

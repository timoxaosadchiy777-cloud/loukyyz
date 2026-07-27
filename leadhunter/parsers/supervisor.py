"""Согласование запущенных парсеров с выбором пользователей.

Парсер — процессный: один на биржу, общий для всех. Запускать его на каждого
пользователя нельзя — это N одинаковых запросов к одному сайту и быстрый бан.
Поэтому правило простое: **биржу опрашиваем, пока она включена хотя бы у
одного пользователя, и не трогаем совсем, если её не выбрал никто.**

Супервизор периодически сверяет список работающих парсеров с этим объединением
и доводит его до нужного состояния. Поэтому включение биржи в боте начинает
работать без перезапуска, а выключение последним пользователем гасит опрос.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from core.models import Order
from core.sources import SOURCES
from parsers.registry import build_one

if TYPE_CHECKING:
    from bot.alerts import Alerter
    from config import Settings
    from core.runtime_config import RuntimeConfigStore
    from database.db import Database
    from parsers.base import BaseParser

log = logging.getLogger(__name__)

#: Как часто сверять состав парсеров с выбором пользователей.
RECONCILE_INTERVAL = 60


class SourceSupervisor:
    """Держит запущенными ровно те парсеры, которые кому-то нужны."""

    def __init__(
        self,
        queue: "asyncio.Queue[Order]",
        settings: "Settings",
        db: "Database",
        alerter: "Alerter | None" = None,
        *,
        config: "RuntimeConfigStore | None" = None,
        interval: int = RECONCILE_INTERVAL,
    ) -> None:
        self._queue = queue
        self._settings = settings
        self._db = db
        self._alerter = alerter
        # Глобальный рубильник владельца из settings.yaml. Пустой список = без
        # ограничения; иначе биржа вне списка не опрашивается, кто бы её ни
        # включил — иначе мы ходили бы на сайт за лидами, которые всё равно
        # отбрасывает пайплайн (см. handle_order).
        self._config = config
        self._interval = max(10, interval)
        self._running: dict[str, tuple[BaseParser, asyncio.Task]] = {}
        self._blocked: set[str] = set()
        # Биржи, чья фабрика отказалась собирать парсер (нет ключа, выключено в
        # .env). Причина не рассосётся сама, поэтому не дёргаем её каждую минуту
        # и не засоряем лог — попробуем снова, когда биржу переключат заново.
        self._unbuildable: set[str] = set()

    @property
    def active(self) -> set[str]:
        """Какие источники опрашиваются прямо сейчас."""
        return set(self._running)

    @property
    def blocked(self) -> set[str]:
        """Биржи, выбранные людьми, но запрещённые владельцем в settings.yaml.

        Нужны экрану «Биржи»: иначе включённая площадка молчала бы без причины.
        """
        return set(self._blocked)

    def parser(self, source_id: str) -> "BaseParser | None":
        entry = self._running.get(source_id)
        return entry[0] if entry else None

    async def reconcile(self) -> tuple[set[str], set[str]]:
        """Приводит состав парсеров к текущему выбору. Возвращает (старт, стоп)."""
        wanted = await self._db.sources_with_subscribers(self._settings.owner_id)
        wanted &= {s.id for s in SOURCES if s.available and s.factory}
        if self._config is not None:
            allowed = self._config.current().enabled_sources
            if allowed:
                self._blocked = wanted - set(allowed)
                wanted &= set(allowed)
            else:
                self._blocked = set()

        # Биржу выключили — забываем, что она не собиралась: включат снова,
        # попробуем ещё раз (вдруг владелец как раз дописал ключ в .env).
        self._unbuildable &= wanted

        started = await self._start_missing(wanted)
        stopped = await self._stop_extra(wanted)
        return started, stopped

    async def _start_missing(self, wanted: set[str]) -> set[str]:
        started: set[str] = set()
        for source in SOURCES:
            if source.id not in wanted or source.id in self._running:
                continue
            if source.id in self._unbuildable:
                continue
            parser = build_one(source, self._queue, self._settings, self._alerter)
            if parser is None:
                # Источник выбран, но не сконфигурирован (нет ключа/URL).
                self._unbuildable.add(source.id)
                continue
            task = asyncio.create_task(parser.run_safe(), name=f"parser:{source.id}")
            self._running[source.id] = (parser, task)
            started.add(source.id)
            log.info("SOURCE %s: парсер запущен (биржу выбрал минимум один пользователь)",
                     source.id.upper())
        return started

    async def _stop_extra(self, wanted: set[str]) -> set[str]:
        stopped: set[str] = set()
        for source_id in list(self._running):
            if source_id in wanted:
                continue
            await self._stop(source_id)
            stopped.add(source_id)
            log.info("SOURCE %s: парсер остановлен — биржу не выбрал никто",
                     source_id.upper())
        return stopped

    async def _stop(self, source_id: str) -> None:
        parser, task = self._running.pop(source_id)
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):  # noqa: BLE001
            pass
        closer = getattr(parser, "aclose", None)
        if closer is not None:
            try:
                await closer()
            except Exception:  # noqa: BLE001 — закрытие сокетов не критично
                log.debug("SOURCE %s: ошибка закрытия", source_id.upper())

    async def poll_now(self, source_id: str) -> int | None:
        """Внеочередной опрос одной биржи (кнопка «Проверить сейчас»).

        ``None`` — источник сейчас не работает; число — сколько новых лидов
        отправлено в обработку.
        """
        parser = self.parser(source_id)
        if parser is None:
            return None
        poll = getattr(parser, "poll_once", None)
        if poll is None:
            return None
        return await poll()

    async def run(self) -> None:
        """Фоновая сверка: включённая в боте биржа стартует без перезапуска."""
        while True:
            try:
                await self.reconcile()
            except Exception:  # noqa: BLE001 — сверка не должна ронять процесс
                log.exception("Не удалось согласовать состав парсеров")
            await asyncio.sleep(self._interval)

    async def aclose(self) -> None:
        for source_id in list(self._running):
            await self._stop(source_id)

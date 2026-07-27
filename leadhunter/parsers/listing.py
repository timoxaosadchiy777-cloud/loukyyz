"""Общий каркас парсера биржи со страницей списка заказов.

Все площадки устроены одинаково: сходить по URL, достать список заказов,
отбросить устаревшие, положить новые в очередь. Различается только разбор
ответа — его и реализует наследник в :meth:`extract`.

Здесь же живёт то, что одинаково важно для всех источников: свежесть лидов,
счётчик подряд идущих неудач и единый формат лога вида
``SOURCE FREELANCER: найдено 7 новых``.
"""

from __future__ import annotations

import abc
import asyncio
import logging

from bot.alerts import Alerter
from config import Settings
from core.freshness import age_hours, is_fresh
from core.models import Order
from parsers.base import BaseParser
from parsers.http import FetchError, HttpFetcher

log = logging.getLogger(__name__)


class ListingParser(BaseParser):
    """Опрос страницы (или API) со списком заказов."""

    #: Человекочитаемое имя для лога: ``SOURCE <LABEL>: найдено N новых``.
    log_label: str = "SOURCE"

    def __init__(
        self,
        queue: "asyncio.Queue[Order]",
        settings: Settings,
        alerter: Alerter | None = None,
        *,
        source: str,
        interval: int = 300,
        pages: int = 1,
        cookie: str = "",
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(queue, alerter)
        self.name = source
        self._source = source
        self._settings = settings
        self._interval = max(60, interval)
        self._pages = max(1, pages)
        self._fetcher = HttpFetcher(
            timeout=settings.source_timeout,
            attempts=settings.retry_attempts,
            base_delay=settings.retry_base_delay,
            cookie=cookie,
            headers=headers,
        )
        self._failures = 0

    # --- Что обязан реализовать наследник ---------------------------------

    @abc.abstractmethod
    def page_url(self, page: int) -> str:
        """Адрес страницы списка заказов."""

    @abc.abstractmethod
    def extract(self, payload: str) -> list[Order]:
        """Разбирает ответ в список заказов. Без сети — чтобы тестировать офлайн."""

    # --- Общий цикл --------------------------------------------------------

    async def run(self) -> None:
        log.info(
            "%s %s: парсер запущен (страниц %s, интервал %s c, сессия %s)",
            self.log_label, self._source.upper(), self._pages, self._interval,
            "есть" if self._fetcher.authenticated else "нет",
        )
        try:
            while True:
                try:
                    await self.poll_once()
                except Exception as exc:  # noqa: BLE001 — цикл не должен умирать
                    await self._on_failure(exc)
                await asyncio.sleep(self._interval)
        finally:
            await self._fetcher.aclose()

    async def poll_once(self) -> int:
        """Один проход. Возвращает число новых лидов, положенных в очередь."""
        emitted = 0
        stale = 0
        seen_before = 0

        for page in range(1, self._pages + 1):
            for order in await self._fetch_page(page):
                if not is_fresh(order, max_age_hours=self._settings.max_lead_age_hours):
                    stale += 1
                    continue
                if await self.emit(order):
                    emitted += 1
                else:
                    seen_before += 1

        # Формат намеренно единый по всем источникам: так в логе сразу видно,
        # какая биржа перестала приносить лиды.
        log.info("%s %s: найдено %s новых", self.log_label, self._source.upper(), emitted)
        if stale or seen_before:
            log.debug(
                "%s %s: пропущено — устаревших %s, уже виденных %s",
                self.log_label, self._source.upper(), stale, seen_before,
            )
        self._failures = 0
        return emitted

    async def _fetch_page(self, page: int) -> list[Order]:
        url = self.page_url(page)
        payload = await self._fetcher.get_text(url, label=f"{self._source}:p{page}")
        orders = self.extract(payload)
        if not orders:
            raise FetchError(
                f"{url}: заказы не распознаны (ответ {len(payload)} б) — "
                f"вероятно, изменился формат. Разбор: parsers/{self._source}_*.py"
            )
        return orders

    async def _on_failure(self, exc: Exception) -> None:
        self._failures += 1
        log.warning(
            "%s %s: опрос не удался (%s подряд): %s",
            self.log_label, self._source.upper(), self._failures, exc,
        )
        # Алёртим со второй неудачи: первая может быть сетевым морганием.
        if self._failures == 2:
            await self.alert(
                f"Источник «{self._source}» не отвечает: {exc}",
                key=f"source-fail:{self._source}",
            )

    async def aclose(self) -> None:
        await self._fetcher.aclose()


def log_freshness(source: str, orders: list[Order]) -> None:
    """Диагностика: сколько лидов пришло с датой публикации и насколько свежих."""
    dated = [o for o in orders if o.published_at is not None]
    if not dated:
        log.debug("SOURCE %s: биржа не отдала дату публикации ни у одного лида",
                  source.upper())
        return
    ages = [age_hours(o) or 0 for o in dated]
    log.debug(
        "SOURCE %s: даты есть у %s/%s, самый свежий %.1f ч, самый старый %.1f ч",
        source.upper(), len(dated), len(orders), min(ages), max(ages),
    )

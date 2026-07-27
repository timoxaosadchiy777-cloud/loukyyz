"""Парсер заказов Kwork (kwork.ru и kwork.com).

Обе площадки — один движок: различаются только хостом и валютой по умолчанию,
поэтому парсер параметризуется источником из реестра (:mod:`core.sources`).

Разбор ответа вынесен в :mod:`parsers.kwork_extract` и не ходит в сеть — сюда
остаются только сетевая часть, цикл опроса и диагностика. Сломался разбор —
чините экстрактор по тестам; сломалась сеть — смотрите здесь.

Kwork часть заказов показывает только залогиненным. Работает и без куки (тогда
видно публичную выдачу), но с ``KWORK_COOKIE`` лидов заметно больше — как это
получить, описано в README.
"""

from __future__ import annotations

import asyncio
import logging

from bot.alerts import Alerter
from config import Settings
from core.models import Order
from parsers.base import BaseParser
from parsers.http import FetchError, HttpFetcher
from parsers.kwork_extract import extract_orders, normalize_budget

log = logging.getLogger(__name__)

# Признаки того, что нас развернуло на форму входа: продолжать бессмысленно.
_LOGGED_OUT_MARKERS = ("/login", "id=\"login-form\"", "Войти на Kwork")

# Слишком короткий ответ — почти наверняка заглушка, капча или блокировка.
_MIN_PAGE_SIZE = 500


class KworkParser(BaseParser):
    """Периодически опрашивает страницу проектов Kwork."""

    def __init__(
        self,
        queue: "asyncio.Queue[Order]",
        settings: Settings,
        alerter: Alerter | None = None,
        *,
        source: str = "kwork",
        base_url: str = "https://kwork.ru",
        projects_path: str = "/projects",
        cookie: str = "",
    ) -> None:
        super().__init__(queue, alerter)
        self.name = source
        self._source = source
        self._base_url = base_url.rstrip("/")
        self._projects_path = projects_path
        self._settings = settings
        self._pages = max(1, settings.kwork_pages)
        self._interval = max(60, settings.kwork_poll_interval)
        self._fetcher = HttpFetcher(
            timeout=settings.kwork_timeout,
            attempts=settings.retry_attempts,
            base_delay=settings.retry_base_delay,
            cookie=cookie,
            headers={"Referer": self._base_url + "/"},
        )
        # Считаем подряд идущие неудачи: одиночный сбой — норма, серия означает
        # смену вёрстки или бан, и об этом нужно сказать владельцу один раз.
        self._failures = 0

    async def run(self) -> None:
        log.info(
            "Kwork-парсер запущен: %s, страниц — %s, интервал — %s c, сессия — %s",
            self._base_url,
            self._pages,
            self._interval,
            "есть" if self._fetcher.authenticated else "нет (только публичная выдача)",
        )
        try:
            while True:
                try:
                    emitted = await self.poll_once()
                    log.info("[%s] новых лидов в очередь — %s", self._source, emitted)
                except Exception as exc:  # noqa: BLE001 — цикл не должен умирать
                    await self._on_failure(exc)
                await asyncio.sleep(self._interval)
        finally:
            # run_safe() гасит исключения снаружи, но сокеты закрыть обязаны мы.
            await self._fetcher.aclose()

    async def poll_once(self) -> int:
        """Один проход по страницам. Возвращает число новых лидов."""
        emitted = 0
        for page in range(1, self._pages + 1):
            orders = await self._fetch_page(page)
            for order in orders:
                normalize_budget(order, usd_rub_rate=self._settings.usd_rub_rate)
                if await self.emit(order):
                    emitted += 1
        self._failures = 0
        return emitted

    async def _fetch_page(self, page: int) -> list[Order]:
        url = self._page_url(page)
        payload = await self._fetcher.get_text(url, label=f"{self._source}:p{page}")

        if len(payload) < _MIN_PAGE_SIZE:
            raise FetchError(
                f"{url}: ответ подозрительно короткий ({len(payload)} б) — "
                "возможна блокировка или капча"
            )
        if self._looks_logged_out(payload):
            raise FetchError(
                f"{url}: биржа показала форму входа — обновите KWORK_COOKIE"
            )

        result = extract_orders(payload, source=self._source, base_url=self._base_url)
        if not result.orders:
            # Отличаем «нет новых заказов» от «сломался разбор»: пустая выдача
            # при большой странице — это почти всегда смена вёрстки.
            raise FetchError(
                f"{url}: заказы не распознаны ни одной стратегией "
                f"(страница {len(payload)} б) — вероятно, изменилась вёрстка"
            )

        log.debug(
            "[%s] страница %s: стратегия '%s', заказов — %s",
            self._source, page, result.strategy, len(result.orders),
        )
        return result.orders

    def _page_url(self, page: int) -> str:
        base = f"{self._base_url}{self._projects_path}"
        return base if page == 1 else f"{base}?page={page}"

    @staticmethod
    def _looks_logged_out(payload: str) -> bool:
        head = payload[:4000]
        return any(marker in head for marker in _LOGGED_OUT_MARKERS)

    async def _on_failure(self, exc: Exception) -> None:
        self._failures += 1
        log.warning("[%s] опрос не удался (%s подряд): %s", self._source, self._failures, exc)
        # Алёртим со второй неудачи: первая может быть сетевым морганием.
        if self._failures == 2:
            await self.alert(
                f"Kwork ({self._source}): {exc}",
                key=f"kwork-fail:{self._source}",
            )

    async def aclose(self) -> None:
        await self._fetcher.aclose()


def build(
    queue: "asyncio.Queue[Order]",
    settings: Settings,
    alerter: Alerter | None,
    source,
) -> KworkParser | None:
    """Фабрика для реестра источников. ``None`` — источник не сконфигурирован."""
    if not settings.kwork_enabled:
        log.info("Kwork выключен (KWORK_ENABLED=false) — парсер не запускается")
        return None

    hosts = {
        "kwork": (settings.kwork_ru_url, settings.kwork_cookie),
        "kwork_com": (settings.kwork_com_url, settings.kwork_com_cookie),
    }
    base_url, cookie = hosts.get(source.id, (settings.kwork_ru_url, settings.kwork_cookie))
    if not base_url:
        return None

    return KworkParser(
        queue,
        settings,
        alerter,
        source=source.id,
        base_url=base_url,
        projects_path=settings.kwork_projects_path,
        cookie=cookie,
    )

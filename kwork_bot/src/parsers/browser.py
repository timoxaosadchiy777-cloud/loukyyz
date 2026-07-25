"""Менеджер браузера Playwright (async) с восстановлением и сохранённой сессией.

- Async context manager: запускает/останавливает Playwright и Chromium.
- Загружает `storage_state.json`, если он есть (логин выполняется оператором вне бота).
- Восстанавливает браузер после падения/дисконнекта и повторяет навигацию с бэкоффом.
- Уважает таймауты навигации/операций.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from playwright.async_api import (
    Browser,
    BrowserContext,
    Page,
    Playwright,
    async_playwright,
)

from config.settings import Settings

log = logging.getLogger(__name__)

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)


class BrowserManager:
    """Владеет жизненным циклом браузера и даёт устойчивую навигацию."""

    def __init__(self, settings: Settings) -> None:
        self._headless = settings.kwork_headless
        self._storage_state = Path(settings.kwork_storage_state)
        self._timeout = settings.kwork_nav_timeout_ms
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self._page: Page | None = None

    async def __aenter__(self) -> "BrowserManager":
        await self.start()
        return self

    async def __aexit__(self, *_exc_info: object) -> None:
        await self.stop()

    async def start(self) -> None:
        self._playwright = await async_playwright().start()
        await self._launch()
        log.info("BrowserManager: браузер запущен (headless=%s)", self._headless)

    async def _launch(self) -> None:
        assert self._playwright is not None
        self._browser = await self._playwright.chromium.launch(headless=self._headless)
        context_kwargs: dict[str, object] = {"user_agent": _USER_AGENT}
        if self._storage_state.exists():
            context_kwargs["storage_state"] = str(self._storage_state)
            log.info("BrowserManager: загружена сессия %s", self._storage_state)
        else:
            log.warning(
                "BrowserManager: файл сессии %s не найден — работаем как гость",
                self._storage_state,
            )
        self._context = await self._browser.new_context(**context_kwargs)
        self._context.set_default_navigation_timeout(self._timeout)
        self._context.set_default_timeout(self._timeout)
        self._page = await self._context.new_page()

    @property
    def page(self) -> Page:
        if self._page is None:
            raise RuntimeError("BrowserManager не запущен — вызовите start()/async with")
        return self._page

    def _healthy(self) -> bool:
        try:
            return (
                self._browser is not None
                and self._browser.is_connected()
                and self._page is not None
                and not self._page.is_closed()
            )
        except Exception:  # noqa: BLE001 — любой сбой считаем нездоровым состоянием
            return False

    async def recover(self) -> None:
        """Пересоздаёт браузер и контекст после падения."""
        log.warning("BrowserManager: восстановление браузера…")
        await self._close_browser()
        await self._launch()

    async def goto(self, url: str, *, retries: int = 3) -> Page:
        """Открывает URL с восстановлением и бэкоффом. Возвращает активную страницу."""
        last_exc: Exception | None = None
        for attempt in range(1, retries + 1):
            try:
                if not self._healthy():
                    await self.recover()
                assert self._page is not None
                await self._page.goto(url, wait_until="domcontentloaded")
                return self._page
            except Exception as exc:  # noqa: BLE001 — навигация/краш → восстановление
                last_exc = exc
                log.warning("BrowserManager: goto %s не удалось (попытка %s/%s): %s",
                            url, attempt, retries, exc)
                if attempt < retries:
                    await self.recover()
                    await asyncio.sleep(min(2 ** attempt, 8))
        assert last_exc is not None
        raise last_exc

    async def save_state(self) -> None:
        """Сохраняет текущую сессию браузера в storage_state.json."""
        if self._context is not None:
            self._storage_state.parent.mkdir(parents=True, exist_ok=True)
            await self._context.storage_state(path=str(self._storage_state))
            log.info("BrowserManager: сессия сохранена в %s", self._storage_state)

    async def _close_browser(self) -> None:
        for closer in (self._context, self._browser):
            try:
                if closer is not None:
                    await closer.close()
            except Exception:  # noqa: BLE001 — закрытие битого объекта не должно падать
                pass
        self._context = None
        self._browser = None
        self._page = None

    async def stop(self) -> None:
        await self._close_browser()
        if self._playwright is not None:
            try:
                await self._playwright.stop()
            except Exception:  # noqa: BLE001
                pass
            self._playwright = None
        log.info("BrowserManager: остановлен")

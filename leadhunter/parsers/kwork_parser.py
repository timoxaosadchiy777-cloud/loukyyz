"""Парсер свежих заказов Kwork через Playwright.

Использует сохранённую браузерную сессию (storage_state), созданную скриптом
`kwork_login.py` — пароли в проекте не хранятся.

⚠️  Kwork периодически меняет вёрстку. CSS-селекторы вынесены в константы ниже —
при поломке парсинга в первую очередь проверяйте и обновляйте именно их. Ни одна
ошибка селектора не роняет процесс: она логируется, парсер ждёт следующей итерации.

Дедупликация уже обработанных проектов выполняется ниже по конвейеру (main.py):
каждый заказ проверяется в SQLite по (source, external_id) до генерации отклика,
поэтому повторно один и тот же проект не обрабатывается.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re

from playwright.async_api import TimeoutError as PWTimeout, async_playwright

from bot.alerts import Alerter
from config import Settings
from core.models import Order
from parsers.base import BaseParser

log = logging.getLogger(__name__)

# --- Селекторы (проверяйте здесь при поломке парсинга) ---
CARD_SELECTOR = "div.want-card, div.card"
TITLE_SELECTOR = "a.wants-card__header-title, .wants-card__header-title a, a[href*='/projects/']"
DESC_SELECTOR = ".wants-card__description-text, .breakwords"
BUDGET_SELECTOR = ".wants-card__price, .want-card__price"

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
_PROJECT_ID_RE = re.compile(r"/projects/(?:view/)?(\d+)")


class KworkParser(BaseParser):
    """Периодически опрашивает биржу Kwork и публикует новые заказы."""

    name = "kwork"

    def __init__(
        self,
        queue: "asyncio.Queue[Order]",
        settings: Settings,
        alerter: Alerter | None = None,
    ) -> None:
        super().__init__(queue, alerter)
        self._settings = settings

    async def run(self) -> None:
        s = self._settings
        if not s.kwork_enabled:
            log.info("Kwork-парсер выключен (KWORK_ENABLED=false)")
            return

        # Логин делается один раз вручную скриптом kwork_login.py — здесь только
        # переиспользуем сохранённую сессию браузера (cookie/localStorage).
        if not os.path.exists(s.kwork_storage_state):
            log.error(
                "Kwork: нет сохранённой сессии («%s»). Выполните один раз: python kwork_login.py",
                s.kwork_storage_state,
            )
            await self.alert(
                "Kwork: не выполнен вход. Запустите `python kwork_login.py` и войдите в аккаунт.",
                key="kwork-auth",
            )
            return

        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=s.kwork_headless)
            context = await browser.new_context(
                user_agent=_USER_AGENT,
                storage_state=s.kwork_storage_state,
            )
            page = await context.new_page()
            try:
                log.info(
                    "Kwork-парсер запущен (интервал: %s с, url: %s)",
                    s.kwork_poll_interval,
                    s.kwork_url,
                )
                while True:
                    try:
                        found = await self._scrape(page)
                        log.debug("Kwork: обработано карточек — %s", found)
                    except Exception as exc:
                        log.exception("Kwork: ошибка при разборе страницы")
                        await self.alert(
                            f"Kwork: ошибка при разборе страницы: {exc}",
                            key="kwork-scrape-fail",
                        )
                    await asyncio.sleep(s.kwork_poll_interval)
            finally:
                await context.close()
                await browser.close()

    async def _scrape(self, page) -> int:
        await page.goto(self._settings.kwork_url, wait_until="domcontentloaded")

        # Сессия истекла? Kwork перекидывает на страницу входа.
        if _looks_logged_out(page):
            log.warning("Kwork: сессия истекла — нужен повторный вход (kwork_login.py).")
            await self.alert(
                "Kwork: сессия истекла. Выполните заново: python kwork_login.py",
                key="kwork-session-expired",
            )
            return 0

        try:
            await page.wait_for_selector(CARD_SELECTOR, timeout=15_000)
        except PWTimeout:
            log.warning(
                "Kwork: карточки проектов не найдены на %s — либо нет новых проектов, "
                "либо изменилась вёрстка (проверьте CARD_SELECTOR).",
                self._settings.kwork_url,
            )
            return 0

        cards = await page.query_selector_all(CARD_SELECTOR)
        emitted = 0
        for card in cards:
            order = await self._parse_card(card)
            if order is not None:
                await self.emit(order)
                emitted += 1

        log.info(
            "Kwork: на странице карточек — %s, отправлено в обработку — %s "
            "(дубликаты отсеются дальше по конвейеру).",
            len(cards),
            emitted,
        )
        return emitted

    async def _parse_card(self, card) -> Order | None:
        try:
            link = await card.query_selector(TITLE_SELECTOR)
            if link is None:
                return None

            title = ((await link.inner_text()) or "").strip()
            href = (await link.get_attribute("href")) or ""
            if not title or not href:
                return None

            url = href if href.startswith("http") else f"https://kwork.ru{href}"

            match = _PROJECT_ID_RE.search(href)
            external_id = match.group(1) if match else url

            description = await _safe_text(card, DESC_SELECTOR)
            budget_raw = await _safe_text(card, BUDGET_SELECTOR)

            return Order(
                source=self.name,
                external_id=external_id,
                title=title,
                url=url,
                description=description or title,
                budget_raw=budget_raw,
            )
        except Exception:
            log.debug("Kwork: не удалось разобрать карточку", exc_info=True)
            return None


async def _safe_text(root, selector: str) -> str:
    """Возвращает текст первого совпадения селектора или пустую строку."""
    element = await root.query_selector(selector)
    if element is None:
        return ""
    return ((await element.inner_text()) or "").strip()


def _looks_logged_out(page) -> bool:
    """Эвристика: Kwork при истёкшей сессии редиректит на /login или /register."""
    url = (page.url or "").lower()
    return "/login" in url or "/register" in url

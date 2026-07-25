"""Парсер заказов Kwork.ru поверх BrowserManager.

Возвращает список `LeadCreate` (без записи в БД — этим занимается сервис-слой).
CSS-селекторы вынесены в константы: при смене вёрстки Kwork правьте здесь. Любая
ошибка разбора отдельной карточки логируется и не роняет остальной сбор.
"""

from __future__ import annotations

import logging
import re

from playwright.async_api import ElementHandle, Page

from parsers.browser import BrowserManager
from schemas.lead import LeadCreate

log = logging.getLogger(__name__)

# --- Селекторы (проверяйте при поломке парсинга) ---
CARD_SELECTOR = "div.want-card, div.card"
TITLE_SELECTOR = "a.wants-card__header-title, .wants-card__header-title a, a[href*='/projects/']"
DESC_SELECTOR = ".wants-card__description-text, .breakwords"
BUDGET_SELECTOR = ".wants-card__price, .want-card__price"

SOURCE = "kwork"
_PROJECT_ID_RE = re.compile(r"/projects/(?:view/)?(\d+)")
_BUDGET_RE = re.compile(r"\d[\d\s.,]*")
_WS_RE = re.compile(r"\s+")


class KworkParser:
    """Читает страницу проектов Kwork и превращает карточки в `LeadCreate`."""

    def __init__(self, browser: BrowserManager, url: str) -> None:
        self._browser = browser
        self._url = url

    async def fetch_leads(self) -> list[LeadCreate]:
        """Открывает биржу и возвращает распознанные заказы."""
        page = await self._browser.goto(self._url)

        if _looks_logged_out(page):
            log.warning("Kwork: похоже, сессия не активна — обновите storage_state.json.")
            return []

        try:
            await page.wait_for_selector(CARD_SELECTOR, timeout=15_000)
        except Exception:  # noqa: BLE001 — нет карточек: пусто/сменилась вёрстка
            log.warning("Kwork: карточки заказов не найдены (нет новых или сменилась вёрстка).")
            return []

        cards = await page.query_selector_all(CARD_SELECTOR)
        leads: list[LeadCreate] = []
        for card in cards:
            lead = await self._parse_card(card)
            if lead is not None:
                leads.append(lead)

        log.info("Kwork: карточек на странице — %s, распознано — %s", len(cards), len(leads))
        return leads

    async def _parse_card(self, card: ElementHandle) -> LeadCreate | None:
        try:
            link = await card.query_selector(TITLE_SELECTOR)
            if link is None:
                return None
            title = _clean(await link.inner_text())
            href = (await link.get_attribute("href")) or ""
            if not title or not href:
                return None

            url = href if href.startswith("http") else f"https://kwork.ru{href}"
            match = _PROJECT_ID_RE.search(href)
            external_id = match.group(1) if match else url

            description = await _safe_text(card, DESC_SELECTOR)
            budget_raw = await _safe_text(card, BUDGET_SELECTOR)
            budget_value = _parse_budget(budget_raw)

            return LeadCreate(
                source=SOURCE,
                external_id=external_id,
                title=title[:512],
                url=url[:1024],
                description=description or title,
                budget_raw=budget_raw[:64],
                budget_value=budget_value,
            )
        except Exception:  # noqa: BLE001 — сбой одной карточки не рушит сбор
            log.debug("Kwork: не удалось разобрать карточку", exc_info=True)
            return None


async def _safe_text(root: ElementHandle, selector: str) -> str:
    element = await root.query_selector(selector)
    if element is None:
        return ""
    return _clean(await element.inner_text())


def _clean(text: str | None) -> str:
    return _WS_RE.sub(" ", (text or "")).strip()


def _parse_budget(text: str) -> int | None:
    """Извлекает числовой бюджет в рублях: «5 000 ₽» → 5000, «договорная» → None."""
    if not text:
        return None
    match = _BUDGET_RE.search(text.replace("\xa0", " "))
    if not match:
        return None
    digits = re.sub(r"\D", "", match.group(0))
    return int(digits) if digits else None


def _looks_logged_out(page: Page) -> bool:
    url = (page.url or "").lower()
    return "/login" in url or "/register" in url

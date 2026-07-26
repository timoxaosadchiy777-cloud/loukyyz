"""Универсальный парсер лидов из RSS/Atom-фидов международных площадок.

Читает список фидов из настройки FEEDS (Upwork saved-search RSS, удалённые
джоб-борды, любой RSS/Atom-источник) и публикует подходящие лиды в общую очередь.

Почему RSS, а не скрапинг: официальные фиды отдают свежие вакансии/проекты без
тяжёлого браузера, капчи и риска бана. Источник модульный — добавить площадку
= дописать ещё один URL в FEEDS.

Дедупликация уже обработанных лидов выполняется ниже по конвейеру (main.py) через
SQLite по (source, external_id), поэтому повторные записи из фида не дублируются.
"""

from __future__ import annotations

import asyncio
import logging
import re
from html import unescape
from urllib.parse import urlparse

import feedparser

from bot.alerts import Alerter
from config import Settings
from core.models import Order
from parsers.base import BaseParser

log = logging.getLogger(__name__)

_TAG_RE = re.compile(r"<[^>]+>")
_USD_RE = re.compile(r"\$\s?(\d[\d,]*)")
_WS_RE = re.compile(r"\s+")

# Некоторые сайты режут дефолтный UA feedparser — представляемся браузером.
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)


class RssParser(BaseParser):
    """Периодически опрашивает список RSS/Atom-фидов и публикует новые лиды."""

    name = "rss"

    def __init__(
        self,
        queue: "asyncio.Queue[Order]",
        settings: Settings,
        alerter: Alerter | None = None,
    ) -> None:
        super().__init__(queue, alerter)
        self._settings = settings

    async def run(self) -> None:
        feeds = self._settings.feeds
        if not feeds:
            log.warning("RSS-парсер выключен: список FEEDS пуст.")
            return

        # Отбор по смыслу выполняет ИИ ниже по конвейеру (ai.scoring): парсер
        # больше не фильтрует по ключевым словам, а отдаёт все свежие лиды.
        log.info(
            "RSS-парсер запущен: фидов — %s, интервал — %s c",
            len(feeds),
            self._settings.feed_poll_interval,
        )
        while True:
            for url in feeds:
                try:
                    emitted = await self._poll_feed(url)
                    log.info("RSS %s: новых лидов в очередь — %s", _host(url), emitted)
                except Exception as exc:
                    log.exception("RSS: ошибка обработки фида %s", url)
                    await self.alert(
                        f"RSS: ошибка фида {_host(url)}: {exc}",
                        key=f"rss-fail:{url}",
                    )
            await asyncio.sleep(self._settings.feed_poll_interval)

    async def _poll_feed(self, url: str) -> int:
        # feedparser сам качает и парсит; выносим в поток, чтобы не блокировать loop.
        parsed = await asyncio.to_thread(feedparser.parse, url, agent=_USER_AGENT)

        status = getattr(parsed, "status", None)
        if isinstance(status, int) and status >= 400:
            log.warning("RSS %s: HTTP %s — фид недоступен.", _host(url), status)
            return 0

        entries = getattr(parsed, "entries", None) or []
        if not entries:
            bozo = getattr(parsed, "bozo_exception", None)
            log.warning("RSS %s: записей нет%s.", _host(url), f" ({bozo})" if bozo else "")
            return 0

        source = _source_from_url(url)
        emitted = 0
        for entry in entries:
            order = self._entry_to_order(entry, source)
            if order is None:
                continue
            # emit() возвращает False для уже отданных в этой сессии лидов —
            # считаем только реально новые, чтобы счётчик не врал.
            if await self.emit(order):
                emitted += 1
        return emitted

    def _entry_to_order(self, entry, source: str) -> Order | None:
        title = _clean(getattr(entry, "title", "") or "")
        link = (getattr(entry, "link", "") or "").strip()
        if not title or not link:
            return None

        external_id = (getattr(entry, "id", "") or link).strip()
        summary = getattr(entry, "summary", "") or getattr(entry, "description", "") or ""
        description = _strip_html(summary)
        budget_raw, budget_value = _extract_budget(f"{summary} {title}")

        return Order(
            source=source,
            external_id=external_id,
            title=title[:200],
            url=link,
            description=description or title,
            budget_raw=budget_raw,
            budget_value=budget_value,
        )


# --- Вспомогательные функции ---

def _strip_html(text: str) -> str:
    """Убирает HTML-теги и нормализует пробелы."""
    return _clean(unescape(_TAG_RE.sub(" ", text)))


def _clean(text: str) -> str:
    return _WS_RE.sub(" ", text).strip()


def _extract_budget(text: str) -> tuple[str, int | None]:
    """Находит первую сумму в долларах: `$150` → ('$150', 150). Иначе ('', None)."""
    match = _USD_RE.search(text or "")
    if not match:
        return "", None
    digits = match.group(1).replace(",", "")
    try:
        return f"${digits}", int(digits)
    except ValueError:
        return "", None


def _source_from_url(url: str) -> str:
    host = (urlparse(url).hostname or "").lower()
    if "upwork" in host:
        return "upwork"
    if "fiverr" in host:
        return "fiverr"
    return "rss"


def _host(url: str) -> str:
    return (urlparse(url).hostname or url).lower()

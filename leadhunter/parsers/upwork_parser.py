"""Парсер Upwork — лента сохранённого поиска (RSS).

Честно о площадке: публичного API на поиск заказов у Upwork нет, а анонимный
скрапинг выдачи упирается в Cloudflare. Единственный рабочий и легальный путь —
RSS сохранённого поиска: он привязан к аккаунту и содержит персональный
``securityToken``. Владелец копирует ссылку из своего Upwork в ``UPWORK_RSS_URL``,
и биржа начинает приносить лиды.

Поэтому парсер не «включается сам»: без ссылки он честно не стартует, а экран
«Биржи» подсказывает, какую переменную заполнить (см. ``Source.needs``).

Разбор — стандартной библиотекой (``xml.etree``), без feedparser: зависимость
одного источника не должна быть обязательной для запуска всего бота.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from html import unescape
from xml.etree import ElementTree

from bot.alerts import Alerter
from config import Settings
from core.models import Order
from parsers.listing import ListingParser

log = logging.getLogger(__name__)

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")
# «Budget: $500» / «Hourly Range: $30.00-$60.00» — Upwork кладёт это в описание.
_BUDGET_RE = re.compile(r"\$\s?(\d[\d,]*(?:\.\d+)?)")
# Идентификатор заказа в ссылке: .../jobs/Some-Title_~021234567890123456789/
_JOB_ID_RE = re.compile(r"~([0-9a-z]+)")


class UpworkParser(ListingParser):
    """Читает RSS сохранённого поиска Upwork."""

    def __init__(
        self,
        queue,
        settings: Settings,
        alerter: Alerter | None = None,
        *,
        source: str = "upwork",
        feed_url: str = "",
    ) -> None:
        super().__init__(
            queue, settings, alerter, source=source,
            interval=settings.source_poll_interval,
            # Фид отдаёт одну страницу — пагинации у него нет.
            pages=1,
            headers={"Accept": "application/rss+xml, application/xml;q=0.9, */*;q=0.8"},
        )
        self._feed_url = feed_url

    def page_url(self, page: int) -> str:
        return self._feed_url

    def extract(self, payload: str) -> list[Order]:
        return extract_feed(payload, source=self._source)


def extract_feed(payload: str, *, source: str = "upwork") -> list[Order]:
    """Разбирает RSS-ленту Upwork в заказы. Без сети — тестируется офлайн."""
    try:
        root = ElementTree.fromstring(payload)
    except ElementTree.ParseError as exc:
        log.warning("SOURCE %s: лента не разобралась как XML: %s", source.upper(), exc)
        return []

    orders: list[Order] = []
    for item in root.iter("item"):
        order = _item_to_order(item, source)
        if order is not None:
            orders.append(order)
    return orders


def _item_to_order(item, source: str) -> Order | None:
    title = _clean(_text(item, "title"))
    url = _text(item, "link").strip()
    if not title or not url:
        return None

    description = _strip_html(_text(item, "description"))
    budget_raw, budget_value = _budget(description)

    return Order(
        source=source,
        external_id=_external_id(item, url),
        title=title[:200],
        url=url,
        description=description or title,
        budget_raw=budget_raw,
        budget_value=budget_value,
        published_at=_published(item),
    )


def _text(item, tag: str) -> str:
    node = item.find(tag)
    return (node.text or "") if node is not None else ""


def _external_id(item, url: str) -> str:
    """Стабильный id заказа: guid, иначе ``~0…`` из ссылки, иначе сама ссылка."""
    guid = _text(item, "guid").strip()
    if guid:
        return guid
    match = _JOB_ID_RE.search(url)
    return match.group(1) if match else url


def _published(item) -> datetime | None:
    raw = _text(item, "pubDate").strip()
    if not raw:
        return None
    try:
        moment = parsedate_to_datetime(raw)
    except (TypeError, ValueError):
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment


def _budget(text: str) -> tuple[str, int | None]:
    """Первая сумма в долларах из описания. Почасовку берём как нижнюю границу."""
    match = _BUDGET_RE.search(text or "")
    if not match:
        return "", None
    digits = match.group(1).replace(",", "")
    try:
        return f"${digits}", int(float(digits))
    except ValueError:
        return "", None


def _strip_html(text: str) -> str:
    return _clean(unescape(_TAG_RE.sub(" ", text or "")))


def _clean(text: str) -> str:
    return _WS_RE.sub(" ", unescape(text or "")).strip()


def build(queue, settings: Settings, alerter: Alerter | None, source):
    """Фабрика для реестра источников (см. :mod:`parsers.registry`)."""
    feed_url = settings.upwork_rss_url.strip()
    if not feed_url:
        # Не ошибка, а незаконченная настройка: говорим ровно, что сделать.
        log.warning(
            "SOURCE UPWORK: парсер не запущен — не задан UPWORK_RSS_URL. "
            "Upwork → Find Work → сохранённый поиск → ссылка RSS; вставьте её в .env"
        )
        return None
    return UpworkParser(queue, settings, alerter, source=source.id, feed_url=feed_url)

"""Разбор HTML-страницы со списком заказов — общий для площадок без API.

PeoplePerHour и Guru отдают обычную вёрстку, поэтому разбор идёт двумя
стратегиями: сначала микроразметка ``application/ld+json`` (она стабильнее
CSS и часто содержит дату публикации), потом карточки по классам.

Модуль чистый: на вход строка, на выход заказы. Живой сайт для тестов не нужен.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone

from core.filters import detect_currency, parse_budget, to_usd
from core.models import Order
from parsers.htmltree import Node, parse_html

log = logging.getLogger(__name__)

_MAX_TITLE = 512
_MAX_DESC = 4000
_MIN_TITLE = 3


@dataclass(frozen=True, slots=True)
class ListingSelectors:
    """Классы вёрстки конкретной площадки. Правятся при смене дизайна."""

    card: tuple[str, ...]
    title: tuple[str, ...]
    description: tuple[str, ...]
    budget: tuple[str, ...]
    date: tuple[str, ...] = ()
    #: Шаблон ссылки на заказ — по нему берётся идентификатор.
    url_pattern: str = r"/(\d+)"


def extract_listings(
    payload: str,
    *,
    source: str,
    base_url: str,
    selectors: ListingSelectors,
    usd_rub_rate: float = 0.0,
) -> list[Order]:
    """Заказы со страницы списка. Пробует микроразметку, затем карточки."""
    tree = parse_html(payload)

    orders = _from_json_ld(tree, source=source, base_url=base_url,
                           usd_rub_rate=usd_rub_rate)
    if orders:
        return orders

    orders = _from_cards(tree, source=source, base_url=base_url,
                         selectors=selectors, usd_rub_rate=usd_rub_rate)
    if orders:
        log.info(
            "[%s] разбор через HTML-карточки — микроразметки на странице нет, "
            "следите за селекторами", source,
        )
    return orders


# --- Микроразметка ---------------------------------------------------------


def _from_json_ld(tree: Node, *, source: str, base_url: str,
                  usd_rub_rate: float) -> list[Order]:
    orders: list[Order] = []
    seen: set[str] = set()

    for script in tree.find_all(tag="script"):
        if "ld+json" not in script.get("type"):
            continue
        raw = "".join(c for c in script.children if isinstance(c, str))
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue

        for node in _walk(data):
            types = node.get("@type")
            types = [types] if isinstance(types, str) else (types or [])
            if not any(t in ("JobPosting", "Product", "Offer") for t in types):
                continue
            order = _from_ld_item(node, source=source, base_url=base_url,
                                  usd_rub_rate=usd_rub_rate)
            if order is not None and order.external_id not in seen:
                seen.add(order.external_id)
                orders.append(order)
    return orders


def _walk(node, depth: int = 0):
    if depth > 12:
        return
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from _walk(value, depth + 1)
    elif isinstance(node, list):
        for item in node:
            yield from _walk(item, depth + 1)


def _from_ld_item(item: dict, *, source: str, base_url: str,
                  usd_rub_rate: float) -> Order | None:
    title = _clean(str(item.get("title") or item.get("name") or ""))
    if len(title) < _MIN_TITLE:
        return None

    url = _clean(str(item.get("url") or item.get("@id") or ""))
    external_id = _id_from_url(url) or url
    if not external_id:
        return None

    budget_raw, currency = _ld_budget(item)
    return _build(
        source=source, external_id=external_id, title=title,
        url=url or base_url, description=_clean(str(item.get("description") or "")),
        budget_raw=budget_raw, currency=currency, usd_rub_rate=usd_rub_rate,
        published_at=_parse_date(item.get("datePosted") or item.get("validFrom")),
    )


def _ld_budget(item: dict) -> tuple[str, str]:
    offers = item.get("offers") or item.get("baseSalary")
    if not isinstance(offers, dict):
        return "", "USD"
    value = offers.get("value")
    if isinstance(value, dict):
        amount = value.get("minValue") or value.get("value") or value.get("maxValue")
        currency = str(value.get("currency") or offers.get("priceCurrency") or "USD")
    else:
        amount = offers.get("price") or value
        currency = str(offers.get("priceCurrency") or "USD")
    if amount in (None, ""):
        return "", currency.upper()
    return f"{amount} {currency.upper()}", currency.upper()


# --- Карточки в вёрстке ----------------------------------------------------


def _from_cards(tree: Node, *, source: str, base_url: str,
                selectors: ListingSelectors, usd_rub_rate: float) -> list[Order]:
    cards: list[Node] = []
    for name in selectors.card:
        cards = tree.find_all(cls=name)
        if cards:
            break

    pattern = re.compile(selectors.url_pattern)
    orders: list[Order] = []
    seen: set[str] = set()

    for card in cards:
        order = _from_card(card, source=source, base_url=base_url,
                           selectors=selectors, pattern=pattern,
                           usd_rub_rate=usd_rub_rate)
        if order is None or order.external_id in seen:
            continue
        seen.add(order.external_id)
        orders.append(order)
    return orders


def _from_card(card: Node, *, source: str, base_url: str,
               selectors: ListingSelectors, pattern: re.Pattern,
               usd_rub_rate: float) -> Order | None:
    link = card.find_any_class(selectors.title)
    title = _clean(link.text()) if link else ""
    href = link.get("href") if link else ""

    if not href:
        # Заголовочный класс переименовали — берём любую ссылку на заказ.
        for anchor in card.find_all(tag="a"):
            if pattern.search(anchor.get("href")):
                href = anchor.get("href")
                title = title or _clean(anchor.text())
                break

    if not href or len(title) < _MIN_TITLE:
        return None

    match = pattern.search(href)
    url = href if href.startswith("http") else f"{base_url.rstrip('/')}{href}"
    external_id = match.group(1) if match else url

    desc_node = card.find_any_class(selectors.description)
    budget_node = card.find_any_class(selectors.budget)
    date_node = card.find_any_class(selectors.date) if selectors.date else None
    budget_raw = _clean(budget_node.text()) if budget_node else ""

    return _build(
        source=source, external_id=external_id, title=title, url=url,
        description=_clean(desc_node.text()) if desc_node else title,
        budget_raw=budget_raw, currency=detect_currency(budget_raw),
        usd_rub_rate=usd_rub_rate,
        published_at=_relative_date(_clean(date_node.text())) if date_node else None,
    )


# --- Общее -----------------------------------------------------------------


def _build(*, source: str, external_id: str, title: str, url: str, description: str,
           budget_raw: str, currency: str, usd_rub_rate: float,
           published_at: datetime | None) -> Order:
    return Order(
        source=source,
        external_id=str(external_id)[:128],
        title=title[:_MAX_TITLE],
        url=url[:1024],
        description=(description or title)[:_MAX_DESC],
        budget_raw=budget_raw[:64],
        budget_value=to_usd(parse_budget(budget_raw), currency,
                            usd_rub_rate=usd_rub_rate),
        budget_currency=currency,
        published_at=published_at,
    )


def _parse_date(raw) -> datetime | None:
    if not raw or not isinstance(raw, str):
        return None
    text = raw.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


_RELATIVE_RE = re.compile(
    r"(\d+)\s*(minute|min|hour|hr|day|week|минут|час|дн|нед)", re.IGNORECASE
)
_UNIT_HOURS = {"minute": 1 / 60, "min": 1 / 60, "минут": 1 / 60,
               "hour": 1, "hr": 1, "час": 1,
               "day": 24, "дн": 24, "week": 168, "нед": 168}


def _relative_date(text: str) -> datetime | None:
    """Понимает «2 hours ago», «3 days ago», «5 минут назад».

    Площадки почти никогда не пишут абсолютную дату в карточке списка, зато
    почти всегда — относительную. Без неё отсечка по свежести не работает.
    """
    match = _RELATIVE_RE.search(text or "")
    if not match:
        return None
    amount = int(match.group(1))
    unit = match.group(2).lower()
    hours = next((h for key, h in _UNIT_HOURS.items() if unit.startswith(key)), None)
    if hours is None:
        return None
    from datetime import timedelta

    return datetime.now(timezone.utc) - timedelta(hours=amount * hours)


def _id_from_url(url: str) -> str:
    match = re.search(r"/(\d{4,})", url or "")
    return match.group(1) if match else ""


def _clean(text: str | None) -> str:
    return re.sub(r"\s+", " ", (text or "")).strip()

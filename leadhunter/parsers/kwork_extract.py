"""Извлечение заказов Kwork из ответа страницы.

Модуль намеренно **чистый**: на вход строка (HTML или JSON), на выходе список
``Order``. Никакой сети — поэтому поведение целиком покрывается тестами на
фикстурах, и разбор можно чинить, не имея доступа к живому сайту.

Устойчивость к смене вёрстки обеспечивают три независимые стратегии, которые
пробуются по очереди — от самой стабильной к самой хрупкой:

1. :func:`from_embedded_json` — состояние страницы, вшитое в ``<script>``
   (``window.__NUXT__`` и подобные). Переживает любой редизайн CSS: мы ищем не
   конкретный контейнер, а объекты, похожие на заказ, по именам полей.
2. :func:`from_json_ld` — микроразметка ``application/ld+json``.
3. :func:`from_html_cards` — карточки в HTML. Самое хрупкое место, поэтому
   селекторы вынесены в константы наверх файла.

Если сработала не первая стратегия — это повод посмотреть логи: значит, сайт
поменялся и запасной путь уже несёт нагрузку.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Iterable, Iterator

from core.filters import RUB, detect_currency, parse_budget, to_usd
from core.models import Order
from parsers.htmltree import Node, parse_html

log = logging.getLogger(__name__)

# --- Селекторы HTML-карточек (правьте здесь, если сломался разбор) ----------
# Совпадение идёт по ПОДСТРОКЕ класса, порядок = приоритет.
CARD_CLASSES = ("want-card", "wants-card", "card-project", "project-card")
TITLE_CLASSES = ("wants-card__header-title", "want-card__header-title", "card__title")
DESC_CLASSES = ("wants-card__description-text", "want-card__description", "breakwords")
BUDGET_CLASSES = ("wants-card__price", "want-card__price", "card__price")

# --- Разбор ссылок и идентификаторов ---------------------------------------
PROJECT_URL_RE = re.compile(r"/projects/(?:view/)?(\d+)")

# Переменные, в которых площадка отдаёт состояние страницы.
_STATE_VARS = (
    "window.__NUXT__",
    "window.__INITIAL_STATE__",
    "window.__PRELOADED_STATE__",
    "window.stateData",
    "window.dataLayer",
)

# Имена полей заказа в JSON. Списки, а не одно имя: Kwork за годы менял их
# несколько раз, и старые ответы всё ещё встречаются в кэше и на .com.
_ID_KEYS = ("id", "wants_id", "want_id", "project_id", "paid_id")
_TITLE_KEYS = ("name", "title", "header", "want_name")
_DESC_KEYS = ("description", "desc", "short_description", "text", "want_description")
_PRICE_KEYS = (
    "priceLimit", "price_limit", "possible_price_limit",
    "price", "budget", "cost", "max_price",
)

# Заказ без заголовка бесполезен, а без id мы не сможем его дедуплицировать.
_MIN_TITLE_LEN = 3
_MAX_TITLE_LEN = 512
_MAX_DESC_LEN = 4000


class ExtractionResult(tuple):
    """``(orders, strategy)`` — какие заказы нашли и каким способом."""

    __slots__ = ()

    def __new__(cls, orders: list[Order], strategy: str) -> "ExtractionResult":
        return super().__new__(cls, (orders, strategy))

    @property
    def orders(self) -> list[Order]:
        return self[0]

    @property
    def strategy(self) -> str:
        return self[1]


def extract_orders(payload: str, *, source: str, base_url: str) -> ExtractionResult:
    """Пробует стратегии по очереди и возвращает первую результативную."""
    strategies = (
        ("embedded-json", from_embedded_json),
        ("json-ld", from_json_ld),
        ("html-cards", from_html_cards),
    )
    for name, strategy in strategies:
        try:
            orders = strategy(payload, source=source, base_url=base_url)
        except Exception:  # noqa: BLE001 — одна сломанная стратегия не отменяет остальные
            log.debug("[%s] стратегия %s упала", source, name, exc_info=True)
            continue
        if orders:
            if name != "embedded-json":
                log.info(
                    "[%s] разбор через запасную стратегию '%s' — вероятно, "
                    "сменилась вёрстка, проверьте селекторы",
                    source, name,
                )
            return ExtractionResult(orders, name)
    return ExtractionResult([], "none")


# --- Стратегия 1: состояние страницы в <script> -----------------------------


def from_embedded_json(payload: str, *, source: str, base_url: str) -> list[Order]:
    """Ищет объекты, похожие на заказ, во вшитом в страницу JSON."""
    orders: list[Order] = []
    seen: set[str] = set()
    for blob in _iter_json_blobs(payload):
        for candidate in _walk_dicts(blob):
            order = _order_from_dict(candidate, source=source, base_url=base_url)
            if order is not None and order.external_id not in seen:
                seen.add(order.external_id)
                orders.append(order)
    return orders


def _iter_json_blobs(payload: str) -> Iterator[Any]:
    """Достаёт JSON из присваиваний вида ``window.X = {...}``."""
    for var in _STATE_VARS:
        start = 0
        while True:
            index = payload.find(var, start)
            if index == -1:
                break
            start = index + len(var)
            equals = payload.find("=", start)
            if equals == -1:
                break
            blob = _balanced_json(payload, equals + 1)
            if blob is not None:
                try:
                    yield json.loads(blob)
                except json.JSONDecodeError:
                    # Часто это JS-объект, а не JSON (кавычки, функции) — пропускаем.
                    log.debug("Не JSON в %s", var)


def _balanced_json(text: str, start: int) -> str | None:
    """Вырезает сбалансированный ``{...}`` или ``[...]``, начиная с ``start``."""
    length = len(text)
    while start < length and text[start] in " \t\r\n":
        start += 1
    if start >= length or text[start] not in "{[":
        return None

    opening = text[start]
    closing = "}" if opening == "{" else "]"
    depth = 0
    in_string = False
    escaped = False

    for index in range(start, length):
        char = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == opening:
            depth += 1
        elif char == closing:
            depth -= 1
            if depth == 0:
                return text[start : index + 1]
    return None


def _walk_dicts(node: Any, depth: int = 0) -> Iterator[dict]:
    """Обходит структуру, отдавая все словари (с ограничением глубины)."""
    if depth > 12:  # защита от самоссылающихся и абсурдно вложенных структур
        return
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from _walk_dicts(value, depth + 1)
    elif isinstance(node, list):
        for item in node:
            yield from _walk_dicts(item, depth + 1)


def _order_from_dict(data: dict, *, source: str, base_url: str) -> Order | None:
    """Превращает словарь в заказ, если он вообще похож на заказ."""
    title = _clean(_first_str(data, _TITLE_KEYS))
    if len(title) < _MIN_TITLE_LEN:
        return None

    raw_id = _first_str(data, _ID_KEYS)
    if not raw_id or not str(raw_id).strip().isdigit():
        return None

    # Отсекаем словари-однофамильцы (категории, пользователи): у настоящего
    # заказа есть либо описание, либо цена.
    description = _clean(_first_str(data, _DESC_KEYS))
    price_raw = _first_value(data, _PRICE_KEYS)
    if not description and price_raw is None:
        return None

    external_id = str(raw_id).strip()
    url = _clean(_first_str(data, ("url", "link", "href"))) or _project_url(
        base_url, external_id
    )
    return _build_order(
        source=source,
        external_id=external_id,
        title=title,
        url=url,
        description=description or title,
        budget_raw=_price_text(price_raw),
    )


def _price_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (int, float)):
        # Число без валюты: у Kwork это всегда рубли.
        return f"{int(value)} ₽"
    return _clean(str(value))


# --- Стратегия 2: микроразметка ---------------------------------------------


def from_json_ld(payload: str, *, source: str, base_url: str) -> list[Order]:
    """Разбирает ``<script type="application/ld+json">``."""
    tree = parse_html(payload)
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
        for item in _iter_ld_items(data):
            order = _order_from_ld(item, source=source, base_url=base_url)
            if order is not None and order.external_id not in seen:
                seen.add(order.external_id)
                orders.append(order)
    return orders


def _iter_ld_items(data: Any) -> Iterator[dict]:
    for node in _walk_dicts(data):
        types = node.get("@type")
        types = [types] if isinstance(types, str) else (types or [])
        if any(t in ("JobPosting", "Product", "Offer", "ListItem") for t in types):
            yield node


def _order_from_ld(item: dict, *, source: str, base_url: str) -> Order | None:
    # ListItem оборачивает настоящий объект в поле item.
    payload = item.get("item") if isinstance(item.get("item"), dict) else item
    title = _clean(_first_str(payload, ("title", "name")))
    if len(title) < _MIN_TITLE_LEN:
        return None

    url = _clean(_first_str(payload, ("url", "@id")))
    match = PROJECT_URL_RE.search(url)
    external_id = match.group(1) if match else url
    if not external_id:
        return None

    offers = payload.get("offers")
    price = ""
    if isinstance(offers, dict):
        price = _price_text(offers.get("price"))
        currency = offers.get("priceCurrency")
        if price and currency and str(currency).upper() != "RUB":
            price = f"{price.split()[0]} {currency}"

    return _build_order(
        source=source,
        external_id=external_id,
        title=title,
        url=url or _project_url(base_url, external_id),
        description=_clean(_first_str(payload, ("description",))) or title,
        budget_raw=price,
    )


# --- Стратегия 3: HTML-карточки ---------------------------------------------


def from_html_cards(payload: str, *, source: str, base_url: str) -> list[Order]:
    """Разбирает карточки заказов из вёрстки."""
    tree = parse_html(payload)
    cards: list[Node] = []
    for name in CARD_CLASSES:
        cards = tree.find_all(cls=name)
        if cards:
            break

    orders: list[Order] = []
    seen: set[str] = set()
    for card in cards:
        order = _order_from_card(card, source=source, base_url=base_url)
        if order is None or order.external_id in seen:
            continue
        seen.add(order.external_id)
        orders.append(order)
    return orders


def _order_from_card(card: Node, *, source: str, base_url: str) -> Order | None:
    link = card.find_any_class(TITLE_CLASSES)
    href = ""
    title = ""

    if link is not None:
        title = _clean(link.text())
        href = link.get("href") or ""
        if not href:
            inner = link.find(tag="a")
            if inner is not None:
                href = inner.get("href")
                title = title or _clean(inner.text())

    if not href:
        # Запасной путь: любая ссылка на проект внутри карточки.
        for anchor in card.find_all(tag="a"):
            candidate = anchor.get("href")
            if PROJECT_URL_RE.search(candidate):
                href = candidate
                title = title or _clean(anchor.text())
                break

    if not href or len(title) < _MIN_TITLE_LEN:
        return None

    match = PROJECT_URL_RE.search(href)
    url = href if href.startswith("http") else f"{base_url.rstrip('/')}{href}"
    external_id = match.group(1) if match else url

    description_node = card.find_any_class(DESC_CLASSES)
    budget_node = card.find_any_class(BUDGET_CLASSES)

    return _build_order(
        source=source,
        external_id=external_id,
        title=title,
        url=url,
        description=_clean(description_node.text()) if description_node else title,
        budget_raw=_clean(budget_node.text()) if budget_node else "",
    )


# --- Общая сборка -----------------------------------------------------------


def _build_order(
    *,
    source: str,
    external_id: str,
    title: str,
    url: str,
    description: str,
    budget_raw: str,
    usd_rub_rate: float = 0.0,
) -> Order:
    """Собирает Order, приводя бюджет к валюте сравнения.

    Курс здесь не применяем: он живёт в настройках и подставляется парсером
    (см. :mod:`parsers.kwork_parser`). Тут только фиксируем валюту, чтобы
    рублёвая сумма не уехала в порог как долларовая.
    """
    currency = detect_currency(budget_raw, default=RUB if budget_raw else RUB)
    value = parse_budget(budget_raw)
    return Order(
        source=source,
        external_id=str(external_id)[:128],
        title=title[:_MAX_TITLE_LEN],
        url=url[:1024],
        description=description[:_MAX_DESC_LEN],
        budget_raw=budget_raw[:64],
        budget_value=to_usd(value, currency, usd_rub_rate=usd_rub_rate)
        if usd_rub_rate
        else value,
        budget_currency=currency,
    )


def normalize_budget(order: Order, *, usd_rub_rate: float) -> Order:
    """Приводит ``budget_value`` заказа к USD по текущему курсу."""
    order.budget_value = to_usd(
        parse_budget(order.budget_raw), order.budget_currency, usd_rub_rate=usd_rub_rate
    )
    return order


def _project_url(base_url: str, external_id: str) -> str:
    return f"{base_url.rstrip('/')}/projects/{external_id}"


def _first_value(data: dict, keys: Iterable[str]) -> Any:
    for key in keys:
        if key in data and data[key] not in (None, ""):
            return data[key]
    return None


def _first_str(data: dict, keys: Iterable[str]) -> str:
    value = _first_value(data, keys)
    if value is None or isinstance(value, (dict, list)):
        return ""
    return str(value)


def _clean(text: str | None) -> str:
    return re.sub(r"\s+", " ", (text or "")).strip()

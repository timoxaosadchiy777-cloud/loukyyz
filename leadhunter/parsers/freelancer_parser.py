"""Парсер Freelancer.com через публичный API.

Единственная из добавленных площадок с официальным открытым API: эндпоинт
``/api/projects/0.1/projects/active`` отдаёт активные проекты JSON-ом, без
ключа и без обхода защиты. Поэтому здесь нет разбора вёрстки — только
сопоставление полей, и ломается он лишь при смене схемы API.

Документация: https://developers.freelancer.com/docs/projects/projects
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from bot.alerts import Alerter
from config import Settings
from core.filters import detect_currency, parse_budget, to_usd
from core.models import Order
from parsers.listing import ListingParser

log = logging.getLogger(__name__)

API_PATH = (
    "/api/projects/0.1/projects/active/"
    "?limit={limit}&offset={offset}"
    "&job_details=true&full_description=true&sort_field=time_updated"
)

_MAX_TITLE = 512
_MAX_DESC = 4000


class FreelancerParser(ListingParser):
    """Активные проекты Freelancer.com."""

    def __init__(self, queue, settings: Settings, alerter: Alerter | None = None,
                 *, source: str = "freelancer", base_url: str = "https://www.freelancer.com",
                 limit: int = 50) -> None:
        super().__init__(
            queue, settings, alerter,
            source=source,
            interval=settings.source_poll_interval,
            pages=settings.source_pages,
            headers={"Accept": "application/json"},
        )
        self._base_url = base_url.rstrip("/")
        self._limit = max(1, min(100, limit))

    def page_url(self, page: int) -> str:
        return self._base_url + API_PATH.format(
            limit=self._limit, offset=(page - 1) * self._limit
        )

    def extract(self, payload: str) -> list[Order]:
        return extract_projects(payload, source=self._source, base_url=self._base_url,
                                usd_rub_rate=self._settings.usd_rub_rate)


def extract_projects(
    payload: str, *, source: str, base_url: str, usd_rub_rate: float = 0.0
) -> list[Order]:
    """Разбирает ответ API в заказы. Чистая функция — тестируется офлайн."""
    try:
        data = json.loads(payload)
    except json.JSONDecodeError:
        return []

    projects = (data.get("result") or {}).get("projects")
    if not isinstance(projects, list):
        return []

    orders: list[Order] = []
    for item in projects:
        order = _to_order(item, source=source, base_url=base_url,
                          usd_rub_rate=usd_rub_rate)
        if order is not None:
            orders.append(order)
    return orders


def _to_order(item, *, source: str, base_url: str, usd_rub_rate: float) -> Order | None:
    if not isinstance(item, dict):
        return None

    project_id = item.get("id")
    title = str(item.get("title") or "").strip()
    if not project_id or len(title) < 3:
        return None

    seo = str(item.get("seo_url") or "").strip()
    url = f"{base_url}/projects/{seo}" if seo else f"{base_url}/projects/{project_id}"

    description = str(
        item.get("description") or item.get("preview_description") or ""
    ).strip()

    budget_raw, currency = _budget(item)
    value = parse_budget(budget_raw)

    return Order(
        source=source,
        external_id=str(project_id),
        title=title[:_MAX_TITLE],
        url=url[:1024],
        description=(description or title)[:_MAX_DESC],
        budget_raw=budget_raw[:64],
        budget_value=to_usd(value, currency, usd_rub_rate=usd_rub_rate),
        budget_currency=currency,
        published_at=_published(item),
    )


def _budget(item: dict) -> tuple[str, str]:
    """Собирает строку бюджета и код валюты из блоков budget/currency."""
    budget = item.get("budget") if isinstance(item.get("budget"), dict) else {}
    currency = item.get("currency") if isinstance(item.get("currency"), dict) else {}
    code = str(currency.get("code") or "USD").upper()
    sign = str(currency.get("sign") or "")

    low, high = budget.get("minimum"), budget.get("maximum")
    if low and high:
        text = f"{sign}{int(low)}–{sign}{int(high)}"
    elif low:
        text = f"от {sign}{int(low)}"
    elif high:
        text = f"до {sign}{int(high)}"
    else:
        return "", code

    # detect_currency работает по символам; код валюты знаем точно, он важнее.
    return text, code if code in ("USD", "RUB") else detect_currency(text)


def _published(item: dict) -> datetime | None:
    """Дата публикации: API отдаёт unix-время в submitdate/time_submitted."""
    for key in ("submitdate", "time_submitted", "time_updated"):
        raw = item.get(key)
        if isinstance(raw, (int, float)) and raw > 0:
            try:
                return datetime.fromtimestamp(float(raw), tz=timezone.utc)
            except (OverflowError, OSError, ValueError):
                continue
    return None


def build(queue, settings: Settings, alerter: Alerter | None, source) -> FreelancerParser | None:
    """Фабрика для реестра источников."""
    if not settings.freelancer_enabled:
        log.info("Freelancer выключен (FREELANCER_ENABLED=false)")
        return None
    return FreelancerParser(queue, settings, alerter, source=source.id,
                            base_url=settings.freelancer_url)

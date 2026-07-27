"""Парсер PeoplePerHour — страница фриланс-проектов.

API у площадки нет, поэтому разбирается обычная выдача: сначала микроразметка
``ld+json`` (там есть дата публикации), затем карточки по классам. Селекторы
собраны в :data:`SELECTORS` — при смене вёрстки правится только этот блок.
"""

from __future__ import annotations

import logging

from bot.alerts import Alerter
from config import Settings
from core.models import Order
from parsers.html_listing import ListingSelectors, extract_listings
from parsers.listing import ListingParser

log = logging.getLogger(__name__)

SELECTORS = ListingSelectors(
    card=("job-listing", "listing-item", "job-card"),
    title=("job-listing__title", "listing-item__title", "job-title"),
    description=("job-listing__description", "listing-item__description", "job-desc"),
    budget=("job-listing__budget", "listing-item__budget", "job-budget"),
    date=("job-listing__posted", "listing-item__date", "posted-date"),
    url_pattern=r"/freelance-jobs?/[^/]*?(\d{4,})",
)


class PeoplePerHourParser(ListingParser):
    def __init__(self, queue, settings: Settings, alerter: Alerter | None = None,
                 *, source: str = "peopleperhour",
                 base_url: str = "https://www.peopleperhour.com") -> None:
        super().__init__(
            queue, settings, alerter, source=source,
            interval=settings.source_poll_interval, pages=settings.source_pages,
            cookie=settings.pph_cookie,
        )
        self._base_url = base_url.rstrip("/")

    def page_url(self, page: int) -> str:
        base = f"{self._base_url}/freelance-jobs"
        return base if page == 1 else f"{base}?page={page}"

    def extract(self, payload: str) -> list[Order]:
        return extract_listings(
            payload, source=self._source, base_url=self._base_url,
            selectors=SELECTORS, usd_rub_rate=self._settings.usd_rub_rate,
        )


def build(queue, settings: Settings, alerter: Alerter | None, source):
    if not settings.pph_enabled:
        log.info("PeoplePerHour выключен (PPH_ENABLED=false)")
        return None
    return PeoplePerHourParser(queue, settings, alerter, source=source.id,
                               base_url=settings.pph_url)

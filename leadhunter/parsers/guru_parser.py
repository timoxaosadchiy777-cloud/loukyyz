"""Парсер Guru.com — страница открытых проектов.

Разбор устроен так же, как у PeoplePerHour: микроразметка, затем карточки.
Селекторы в :data:`SELECTORS`.
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
    card=("jobRecord", "job-record", "serviceItem"),
    title=("jobRecord__title", "job-title", "jobRecord__link"),
    description=("jobRecord__descText", "job-description", "jobRecord__desc"),
    budget=("jobRecord__budget", "job-budget", "jobRecord__price"),
    date=("jobRecord__posted", "job-posted", "posted"),
    url_pattern=r"/jobs?/[^/]*?(\d{4,})",
)


class GuruParser(ListingParser):
    def __init__(self, queue, settings: Settings, alerter: Alerter | None = None,
                 *, source: str = "guru", base_url: str = "https://www.guru.com") -> None:
        super().__init__(
            queue, settings, alerter, source=source,
            interval=settings.source_poll_interval, pages=settings.source_pages,
            cookie=settings.guru_cookie,
        )
        self._base_url = base_url.rstrip("/")

    def page_url(self, page: int) -> str:
        base = f"{self._base_url}/d/jobs/"
        return base if page == 1 else f"{base}?page={page}"

    def extract(self, payload: str) -> list[Order]:
        return extract_listings(
            payload, source=self._source, base_url=self._base_url,
            selectors=SELECTORS, usd_rub_rate=self._settings.usd_rub_rate,
        )


def build(queue, settings: Settings, alerter: Alerter | None, source):
    if not settings.guru_enabled:
        log.info("Guru выключен (GURU_ENABLED=false)")
        return None
    return GuruParser(queue, settings, alerter, source=source.id,
                      base_url=settings.guru_url)

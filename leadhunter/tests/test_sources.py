"""Тесты агрегатора источников: реестр, sources_settings, свежесть, парсеры."""

from __future__ import annotations

import asyncio
import json
import time
from datetime import datetime, timedelta, timezone

import pytest_asyncio

from core.freshness import DEFAULT_MAX_AGE_HOURS, age_hours, cutoff, is_fresh
from core.models import Order
from core.sources import SOURCES, default_enabled_ids, get_source
from database.db import Database
from parsers.freelancer_parser import extract_projects
from parsers.html_listing import ListingSelectors, extract_listings

USER = 501
OTHER = 502


def _order(hours_ago: float | None = 1, **kwargs) -> Order:
    published = (
        datetime.now(timezone.utc) - timedelta(hours=hours_ago)
        if hours_ago is not None else None
    )
    base = dict(source="freelancer", external_id="1", title="t", url="u",
                description="d", published_at=published)
    base.update(kwargs)
    return Order(**base)


# --- Реестр ----------------------------------------------------------------


def test_all_requested_exchanges_are_registered() -> None:
    registered = {s.id for s in SOURCES}
    assert {"kwork", "kwork_com", "upwork", "fiverr", "freelancer",
            "peopleperhour", "guru", "weworkremotely"} <= registered


def test_upwork_and_fiverr_are_marked_unavailable_with_reason() -> None:
    """Не заглушки: у площадок нет публичной ленты заказов, и это сказано."""
    for source_id in ("upwork", "fiverr"):
        source = get_source(source_id)
        assert source.available is False
        assert source.note, f"{source_id}: причина не указана"


def test_weworkremotely_is_off_by_default() -> None:
    """RSS — вспомогательный источник, а не основной."""
    assert get_source("weworkremotely").default_enabled is False
    assert "weworkremotely" not in default_enabled_ids()


def test_real_exchanges_are_on_by_default() -> None:
    assert {"kwork", "freelancer", "guru"} <= set(default_enabled_ids())


def test_every_available_source_has_parser_factory() -> None:
    for source in SOURCES:
        if source.available:
            assert source.factory, f"{source.id}: нет фабрики парсера"


# --- sources_settings ------------------------------------------------------


@pytest_asyncio.fixture
async def db(tmp_path):
    database = Database(str(tmp_path / "sources.db"))
    await database.connect()
    try:
        yield database
    finally:
        await database.close()


async def test_new_user_gets_registry_defaults(db) -> None:
    assert await db.get_enabled_sources(USER) == default_enabled_ids()


async def test_toggle_persists_per_user(db) -> None:
    await db.toggle_source(USER, "kwork")

    assert "kwork" not in await db.get_enabled_sources(USER)
    assert "kwork" in await db.get_enabled_sources(OTHER)  # чужой выбор не задет


async def test_enabling_default_off_source(db) -> None:
    assert await db.toggle_source(USER, "weworkremotely") is True
    assert "weworkremotely" in await db.get_enabled_sources(USER)


async def test_explicit_choice_survives_new_source_in_registry(db) -> None:
    """Строки нет → берём дефолт реестра, поэтому новая биржа появляется сама."""
    await db.set_source_enabled(USER, "kwork", False)
    enabled = await db.get_enabled_sources(USER)

    assert "kwork" not in enabled
    assert "freelancer" in enabled  # про неё пользователь не высказывался


async def test_unavailable_source_never_enabled(db) -> None:
    await db.set_source_enabled(USER, "upwork", True)
    assert "upwork" not in await db.get_enabled_sources(USER)


async def test_settings_carry_resolved_sources(db) -> None:
    settings = await db.get_user_settings(USER)
    assert settings.sources_explicit is True
    assert settings.source_enabled("weworkremotely") is False
    assert settings.source_enabled("guru") is True


async def test_disabling_everything_means_nothing(db) -> None:
    """Пустой список из таблицы — это «выключено всё», а не «включено всё»."""
    for source in SOURCES:
        if source.available:
            await db.set_source_enabled(USER, source.id, False)

    settings = await db.get_user_settings(USER)
    assert settings.sources == ()
    assert settings.source_enabled("guru") is False


async def test_old_csv_choice_is_migrated(tmp_path) -> None:
    """Выбор бирж из прошлой версии не должен потеряться."""
    import aiosqlite

    from core.user_settings import UserSettings

    path = tmp_path / "legacy.db"
    database = Database(str(path))
    await database.connect()
    await database.save_user_settings(USER, UserSettings(onboarded=True))
    await database.close()

    async with aiosqlite.connect(str(path)) as conn:
        await conn.execute("UPDATE user_settings SET sources = 'kwork' WHERE telegram_id = ?",
                           (USER,))
        await conn.execute("DELETE FROM sources_settings")
        await conn.commit()

    database = Database(str(path))
    await database.connect()  # запускает миграцию
    try:
        enabled = await database.get_enabled_sources(USER)
        assert enabled == ("kwork",)
    finally:
        await database.close()


# --- Свежесть --------------------------------------------------------------


def test_fresh_lead_passes() -> None:
    assert is_fresh(_order(hours_ago=1)) is True
    assert is_fresh(_order(hours_ago=23)) is True


def test_stale_lead_is_rejected() -> None:
    assert is_fresh(_order(hours_ago=25)) is False
    assert is_fresh(_order(hours_ago=24 * 7)) is False


def test_lead_without_date_is_kept() -> None:
    """Часть площадок дату не отдаёт — терять их лиды нельзя."""
    assert is_fresh(_order(hours_ago=None)) is True


def test_zero_limit_disables_cutoff() -> None:
    assert is_fresh(_order(hours_ago=1000), max_age_hours=0) is True


def test_naive_datetime_is_treated_as_utc() -> None:
    order = _order()
    order.published_at = datetime.utcnow() - timedelta(hours=2)
    assert 1.5 < age_hours(order) < 2.5


def test_cutoff_is_in_the_past() -> None:
    assert cutoff(DEFAULT_MAX_AGE_HOURS) < datetime.now(timezone.utc)


# --- Freelancer API --------------------------------------------------------


def _api(projects) -> str:
    return json.dumps({"status": "success", "result": {"projects": projects}})


def test_freelancer_extracts_fields() -> None:
    payload = _api([{
        "id": 900001, "title": "Build a Telegram bot",
        "seo_url": "python/telegram-bot", "description": "aiogram + payments",
        "submitdate": int(time.time()) - 3600,
        "budget": {"minimum": 250, "maximum": 750},
        "currency": {"code": "USD", "sign": "$"},
    }])
    order = extract_projects(payload, source="freelancer",
                             base_url="https://www.freelancer.com")[0]

    assert order.external_id == "900001"
    assert order.title == "Build a Telegram bot"
    assert order.url.endswith("/projects/python/telegram-bot")
    assert order.budget_raw == "$250–$750"
    assert order.budget_value == 250
    assert order.published_at is not None
    assert is_fresh(order) is True


def test_freelancer_stale_project_detected() -> None:
    payload = _api([{
        "id": 2, "title": "Old job", "seo_url": "x", "description": "d",
        "submitdate": int(time.time()) - 60 * 60 * 100,
        "budget": {"minimum": 30}, "currency": {"code": "USD", "sign": "$"},
    }])
    assert is_fresh(extract_projects(payload, source="freelancer",
                                     base_url="https://f.com")[0]) is False


def test_freelancer_survives_broken_payload() -> None:
    assert extract_projects("не json", source="freelancer", base_url="u") == []
    assert extract_projects("{}", source="freelancer", base_url="u") == []
    assert extract_projects(_api(["мусор", None, {}]), source="freelancer",
                            base_url="u") == []


# --- HTML-листинги (PPH / Guru) --------------------------------------------

_SELECTORS = ListingSelectors(
    card=("job-listing",), title=("job-title",), description=("job-desc",),
    budget=("job-budget",), date=("job-posted",), url_pattern=r"/jobs?/(\d+)",
)

_LD_PAGE = """
<html><head><script type="application/ld+json">
{"@type":"JobPosting","title":"Python automation script",
 "url":"https://www.guru.com/jobs/123456","description":"Automate reports",
 "datePosted":"%s",
 "offers":{"@type":"Offer","price":400,"priceCurrency":"USD"}}
</script></head><body>x</body></html>
""" % (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()

_CARDS_PAGE = """
<html><body>
<div class="job-listing">
  <a class="job-title" href="/jobs/778899">Build an API integration</a>
  <div class="job-desc">Connect CRM with webhooks</div>
  <div class="job-budget">$300</div>
  <div class="job-posted">3 hours ago</div>
</div>
</body></html>
"""


def test_html_listing_prefers_microdata() -> None:
    orders = extract_listings(_LD_PAGE, source="guru",
                              base_url="https://www.guru.com", selectors=_SELECTORS)
    assert len(orders) == 1
    assert orders[0].external_id == "123456"
    assert orders[0].budget_value == 400
    assert is_fresh(orders[0]) is True


def test_html_listing_falls_back_to_cards() -> None:
    orders = extract_listings(_CARDS_PAGE, source="peopleperhour",
                              base_url="https://www.pph.com", selectors=_SELECTORS)
    assert len(orders) == 1
    order = orders[0]
    assert order.external_id == "778899"
    assert order.budget_raw == "$300"
    assert order.url == "https://www.pph.com/jobs/778899"
    # Относительная дата разобрана — без неё отсечка по свежести не работает.
    assert 2.5 < age_hours(order) < 3.5


def test_html_listing_on_unknown_markup() -> None:
    assert extract_listings("<html><body>ничего</body></html>", source="guru",
                            base_url="u", selectors=_SELECTORS) == []


# --- Единый формат лога ----------------------------------------------------


async def test_poll_logs_per_source(caplog) -> None:
    """В логе должно быть видно, какая биржа сколько принесла."""
    import logging

    from parsers.listing import ListingParser

    class _Fake(ListingParser):
        def page_url(self, page: int) -> str:
            return "https://example.com"

        def extract(self, payload: str) -> list[Order]:
            return [_order(external_id="a"), _order(external_id="b")]

    class _S:
        source_timeout = 5.0
        retry_attempts = 1
        retry_base_delay = 0.1
        max_lead_age_hours = 24

    parser = _Fake(asyncio.Queue(), _S(), None, source="freelancer")

    class _F:
        authenticated = False

        async def get_text(self, url, *, label=""):
            return "payload"

        async def aclose(self):
            pass

    parser._fetcher = _F()

    with caplog.at_level(logging.INFO):
        emitted = await parser.poll_once()

    assert emitted == 2
    assert "SOURCE FREELANCER: найдено 2 новых" in caplog.text


async def test_stale_leads_are_not_emitted() -> None:
    from parsers.listing import ListingParser

    class _Fake(ListingParser):
        def page_url(self, page: int) -> str:
            return "https://example.com"

        def extract(self, payload: str) -> list[Order]:
            return [_order(hours_ago=1, external_id="fresh"),
                    _order(hours_ago=100, external_id="stale")]

    class _S:
        source_timeout = 5.0
        retry_attempts = 1
        retry_base_delay = 0.1
        max_lead_age_hours = 24

    queue: asyncio.Queue = asyncio.Queue()
    parser = _Fake(queue, _S(), None, source="guru")

    class _F:
        authenticated = False

        async def get_text(self, url, *, label=""):
            return "payload"

        async def aclose(self):
            pass

    parser._fetcher = _F()

    assert await parser.poll_once() == 1
    assert queue.get_nowait().external_id == "fresh"

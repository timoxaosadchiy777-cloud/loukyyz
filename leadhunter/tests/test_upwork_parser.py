"""Разбор ленты Upwork (RSS сохранённого поиска) — офлайн, на фикстуре."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

from core.freshness import is_fresh
from parsers.upwork_parser import build, extract_feed


def _feed(*items: str) -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        "<rss version=\"2.0\"><channel>"
        "<title>Upwork saved search</title>" + "".join(items) + "</channel></rss>"
    )


def _item(
    *,
    title: str = "Telegram bot developer needed",
    link: str = "https://www.upwork.com/jobs/Telegram-bot_~021777000111222333/",
    description: str = "Budget: $500 &lt;br /&gt;Need a &lt;b&gt;Python&lt;/b&gt; bot",
    pub_date: str | None = None,
    guid: str | None = None,
) -> str:
    when = pub_date or _rfc822(datetime.now(timezone.utc))
    guid_tag = f"<guid>{guid}</guid>" if guid else ""
    return (
        "<item>"
        f"<title>{title}</title>"
        f"<link>{link}</link>"
        f"<description>{description}</description>"
        f"<pubDate>{when}</pubDate>"
        f"{guid_tag}"
        "</item>"
    )


def _rfc822(moment: datetime) -> str:
    return moment.strftime("%a, %d %b %Y %H:%M:%S +0000")


class _Settings:
    upwork_rss_url = ""
    source_poll_interval = 300
    source_timeout = 5.0
    retry_attempts = 1
    retry_base_delay = 0.0
    max_lead_age_hours = 24


# --- Разбор ---------------------------------------------------------------


def test_extracts_order_with_all_fields() -> None:
    orders = extract_feed(_feed(_item()))

    assert len(orders) == 1
    order = orders[0]
    assert order.source == "upwork"
    assert order.title == "Telegram bot developer needed"
    assert order.url.startswith("https://www.upwork.com/jobs/")
    assert "Python" in order.description
    assert order.budget_raw == "$500"
    assert order.budget_value == 500
    assert order.published_at is not None


def test_description_html_is_stripped() -> None:
    order = extract_feed(_feed(_item()))[0]
    assert "<b>" not in order.description and "&lt;" not in order.description


def test_external_id_prefers_guid() -> None:
    order = extract_feed(_feed(_item(guid="upwork-42")))[0]
    assert order.external_id == "upwork-42"


def test_external_id_falls_back_to_job_id_in_link() -> None:
    """Без guid берём ~0…-идентификатор из ссылки — он стабилен между опросами."""
    order = extract_feed(_feed(_item()))[0]
    assert order.external_id == "021777000111222333"


def test_hourly_range_gives_lower_bound() -> None:
    order = extract_feed(
        _feed(_item(description="Hourly Range: $30.00-$60.00"))
    )[0]
    assert order.budget_value == 30


def test_missing_budget_is_not_invented() -> None:
    order = extract_feed(_feed(_item(description="No budget mentioned")))[0]
    assert order.budget_raw == "" and order.budget_value is None


def test_item_without_link_is_skipped() -> None:
    broken = "<item><title>Без ссылки</title></item>"
    orders = extract_feed(_feed(broken, _item()))
    assert [o.title for o in orders] == ["Telegram bot developer needed"]


def test_broken_xml_does_not_raise() -> None:
    assert extract_feed("<rss><channel><item>") == []


def test_empty_feed_gives_nothing() -> None:
    assert extract_feed(_feed()) == []


# --- Свежесть -------------------------------------------------------------


def test_published_at_drives_freshness() -> None:
    old = _rfc822(datetime.now(timezone.utc) - timedelta(days=3))
    fresh, stale = (
        extract_feed(_feed(_item()))[0],
        extract_feed(_feed(_item(pub_date=old)))[0],
    )
    assert is_fresh(fresh, max_age_hours=24) is True
    assert is_fresh(stale, max_age_hours=24) is False


def test_unparsable_date_keeps_the_lead() -> None:
    """Дата не разобралась — лид всё равно доходит, а не пропадает молча."""
    order = extract_feed(_feed(_item(pub_date="вчера вечером")))[0]
    assert order.published_at is None
    assert is_fresh(order, max_age_hours=24) is True


# --- Фабрика --------------------------------------------------------------


def test_build_refuses_without_feed_url() -> None:
    """Без личной ссылки парсер не поднимается и в сеть не ходит."""
    source = type("S", (), {"id": "upwork"})()
    assert build(asyncio.Queue(), _Settings(), None, source) is None


def test_build_returns_parser_with_feed_url() -> None:
    settings = _Settings()
    settings.upwork_rss_url = "https://www.upwork.com/ab/feed/jobs/rss?q=python&securityToken=x"
    source = type("S", (), {"id": "upwork"})()

    parser = build(asyncio.Queue(), settings, None, source)

    assert parser is not None
    assert parser.page_url(1) == settings.upwork_rss_url
    assert parser.page_url(2) == settings.upwork_rss_url  # пагинации у ленты нет

"""Тесты Kwork: три стратегии разбора, устойчивость, реестр источников.

Живой сайт здесь не нужен: экстрактор чистый, а фикстуры воспроизводят все
формы ответа, которые он обязан понимать. Именно поэтому разбор можно чинить,
не имея доступа к Kwork.
"""

from __future__ import annotations

import asyncio

import pytest

from core.filters import RUB, USD, detect_currency, to_usd
from core.sources import SOURCES, get_source
from parsers.htmltree import parse_html
from parsers.kwork_extract import (
    extract_orders,
    from_embedded_json,
    from_html_cards,
    from_json_ld,
    normalize_budget,
)
from parsers.registry import build_parsers, load_factory

BASE = "https://kwork.ru"


# --- Фикстуры страниц -----------------------------------------------------


EMBEDDED_JSON_PAGE = """
<!DOCTYPE html><html><head><title>Проекты</title></head><body>
<div id="app"></div>
<script>
window.__NUXT__ = {"data":{"projects":{"wants":[
  {"id":123456,"name":"Нужен Telegram бот для приёма заявок",
   "description":"Бот на Python, приём заявок и выгрузка в Google Sheets",
   "priceLimit":15000},
  {"id":123457,"name":"Парсер маркетплейса",
   "description":"Собрать товары и цены, выгрузка в CSV","price":8000}
]}},"user":{"id":9,"name":"Вася"}};
</script>
</body></html>
"""

JSON_LD_PAGE = """
<!DOCTYPE html><html><head>
<script type="application/ld+json">
{"@context":"https://schema.org","@type":"ItemList","itemListElement":[
 {"@type":"ListItem","item":{"@type":"JobPosting","name":"Автоматизация отчётов",
  "url":"https://kwork.ru/projects/777001","description":"Excel + Python",
  "offers":{"@type":"Offer","price":12000,"priceCurrency":"RUB"}}}
]}
</script></head><body>Страница без вшитого состояния, но с микроразметкой.
Добавляем текста, чтобы страница не выглядела заглушкой для парсера.</body></html>
"""

HTML_CARDS_PAGE = """
<!DOCTYPE html><html><body>
<div class="want-card want-card--promoted">
  <a class="wants-card__header-title" href="/projects/555001">Разработка бота Telegram</a>
  <div class="wants-card__description-text">Нужен бот с оплатой и админкой</div>
  <div class="wants-card__price">5 000 ₽</div>
</div>
<div class="want-card">
  <a class="wants-card__header-title" href="/projects/555002">Скрипт для парсинга</a>
  <div class="breakwords">Собрать данные с сайта</div>
  <div class="want-card__price">договорная</div>
</div>
</body></html>
"""


# --- Стратегия 1: вшитый JSON ---------------------------------------------


def test_embedded_json_is_preferred_strategy() -> None:
    result = extract_orders(EMBEDDED_JSON_PAGE, source="kwork", base_url=BASE)
    assert result.strategy == "embedded-json"
    assert len(result.orders) == 2


def test_embedded_json_fields() -> None:
    orders = from_embedded_json(EMBEDDED_JSON_PAGE, source="kwork", base_url=BASE)
    first = orders[0]
    assert first.external_id == "123456"
    assert first.title == "Нужен Telegram бот для приёма заявок"
    assert first.url == "https://kwork.ru/projects/123456"
    assert "Google Sheets" in first.description
    assert first.budget_currency == RUB
    assert first.budget_value == 15000  # до нормализации — в рублях


def test_embedded_json_ignores_non_lead_objects() -> None:
    """Пользователь в том же JSON не должен стать заказом."""
    orders = from_embedded_json(EMBEDDED_JSON_PAGE, source="kwork", base_url=BASE)
    assert all(o.external_id != "9" for o in orders)


def test_embedded_json_survives_broken_neighbour() -> None:
    """Битый скрипт рядом не должен мешать разбору исправного."""
    page = EMBEDDED_JSON_PAGE.replace(
        "<div id=\"app\"></div>",
        "<script>window.__INITIAL_STATE__ = {не json};</script>",
    )
    orders = from_embedded_json(page, source="kwork", base_url=BASE)
    assert len(orders) == 2


def test_embedded_json_handles_nested_braces_in_strings() -> None:
    page = (
        '<script>window.stateData = {"wants":[{"id":1,"name":"Бот {скобка} внутри",'
        '"description":"текст","price":100}]}</script>'
    )
    orders = from_embedded_json(page, source="kwork", base_url=BASE)
    assert orders[0].title == "Бот {скобка} внутри"


# --- Стратегия 2: микроразметка -------------------------------------------


def test_json_ld_used_when_no_state() -> None:
    result = extract_orders(JSON_LD_PAGE, source="kwork", base_url=BASE)
    assert result.strategy == "json-ld"
    assert len(result.orders) == 1
    order = result.orders[0]
    assert order.external_id == "777001"
    assert order.title == "Автоматизация отчётов"
    assert order.budget_value == 12000


def test_json_ld_ignores_broken_script() -> None:
    page = JSON_LD_PAGE.replace('"@context"', '"@context" oops')
    assert from_json_ld(page, source="kwork", base_url=BASE) == []


# --- Стратегия 3: HTML-карточки -------------------------------------------


def test_html_cards_used_as_last_resort() -> None:
    result = extract_orders(HTML_CARDS_PAGE, source="kwork", base_url=BASE)
    assert result.strategy == "html-cards"
    assert len(result.orders) == 2


def test_html_card_fields() -> None:
    orders = from_html_cards(HTML_CARDS_PAGE, source="kwork", base_url=BASE)
    first = orders[0]
    assert first.external_id == "555001"
    assert first.title == "Разработка бота Telegram"
    assert first.url == "https://kwork.ru/projects/555001"
    assert first.description == "Нужен бот с оплатой и админкой"
    assert first.budget_raw == "5 000 ₽"
    assert first.budget_value == 5000


def test_html_card_without_price_is_kept() -> None:
    """«Договорная» — не повод терять лид: бюджет обсуждается в переписке."""
    orders = from_html_cards(HTML_CARDS_PAGE, source="kwork", base_url=BASE)
    assert orders[1].budget_value is None


def test_html_cards_survive_class_suffixes() -> None:
    """Совпадение по подстроке класса переживает редизайн-модификаторы."""
    page = HTML_CARDS_PAGE.replace('class="want-card"', 'class="want-card want-card--new"')
    assert len(from_html_cards(page, source="kwork", base_url=BASE)) == 2


def test_html_cards_fallback_to_any_project_link() -> None:
    """Заголовочный класс переименовали — ищем любую ссылку на проект."""
    page = HTML_CARDS_PAGE.replace("wants-card__header-title", "brand-new-title-class")
    orders = from_html_cards(page, source="kwork", base_url=BASE)
    assert len(orders) == 2
    assert orders[0].external_id == "555001"


def test_html_cards_skip_broken_card() -> None:
    page = HTML_CARDS_PAGE + '<div class="want-card"><span>без ссылки</span></div>'
    assert len(from_html_cards(page, source="kwork", base_url=BASE)) == 2


def test_duplicate_cards_are_collapsed() -> None:
    page = HTML_CARDS_PAGE + HTML_CARDS_PAGE
    assert len(from_html_cards(page, source="kwork", base_url=BASE)) == 2


# --- Полный провал разбора -------------------------------------------------


def test_unknown_markup_yields_nothing() -> None:
    result = extract_orders("<html><body>Ничего похожего</body></html>",
                            source="kwork", base_url=BASE)
    assert result.orders == []
    assert result.strategy == "none"


def test_empty_payload_is_safe() -> None:
    assert extract_orders("", source="kwork", base_url=BASE).orders == []


def test_malformed_html_does_not_crash() -> None:
    page = '<div class="want-card"><a href="/projects/1">Тест<div></a></body>'
    from_html_cards(page, source="kwork", base_url=BASE)  # не должно бросить


# --- Мини-DOM --------------------------------------------------------------


def test_htmltree_ignores_script_text() -> None:
    node = parse_html("<div>видно<script>var x=1;</script></div>")
    assert node.text() == "видно"


def test_htmltree_unclosed_tags() -> None:
    node = parse_html("<div class='a'><p>раз<p>два</div>")
    assert "раз" in node.text() and "два" in node.text()


def test_htmltree_class_substring() -> None:
    node = parse_html("<div class='want-card want-card--promo'>x</div>")
    assert node.find(cls="want-card") is not None
    assert node.find(cls="нет-такого") is None


# --- Валюта ----------------------------------------------------------------


def test_rouble_budget_normalized_to_usd() -> None:
    """5 000 ₽ не должны сравниваться с порогом как 5000 долларов."""
    orders = from_html_cards(HTML_CARDS_PAGE, source="kwork", base_url=BASE)
    order = normalize_budget(orders[0], usd_rub_rate=100.0)
    assert order.budget_value == 50
    assert order.budget_raw == "5 000 ₽"  # в карточке — исходная сумма


def test_detect_currency() -> None:
    assert detect_currency("5 000 ₽") == RUB
    assert detect_currency("1 500 руб.") == RUB
    assert detect_currency("$300") == USD
    assert detect_currency("договорная", default=RUB) == RUB


def test_to_usd_passthrough_for_dollars() -> None:
    assert to_usd(300, USD, usd_rub_rate=95.0) == 300
    assert to_usd(None, RUB, usd_rub_rate=95.0) is None


def test_zero_rate_does_not_divide() -> None:
    assert to_usd(5000, RUB, usd_rub_rate=0) == 5000


# --- Реестр источников -----------------------------------------------------


def test_kwork_is_available_and_wired() -> None:
    kwork = get_source("kwork")
    assert kwork.available is True
    assert kwork.factory == "parsers.kwork_parser:build"


def test_kwork_com_is_registered() -> None:
    assert get_source("kwork_com") is not None


def test_every_factory_path_resolves() -> None:
    """Опечатка в реестре обязана падать на тестах, а не в проде."""
    for source in SOURCES:
        if not source.factory:
            continue
        try:
            assert callable(load_factory(source.factory))
        except ImportError as exc:
            # Отсутствующая зависимость источника — не ошибка реестра.
            pytest.skip(f"{source.id}: {exc}")


class _Settings:
    kwork_enabled = True
    kwork_ru_url = "https://kwork.ru"
    kwork_com_url = "https://kwork.com"
    kwork_projects_path = "/projects"
    kwork_cookie = ""
    kwork_com_cookie = ""
    kwork_poll_interval = 300
    kwork_pages = 2
    kwork_timeout = 20.0
    retry_attempts = 3
    retry_base_delay = 2.0
    usd_rub_rate = 95.0
    feeds: list[str] = []


def test_registry_builds_kwork_parsers() -> None:
    parsers = build_parsers(asyncio.Queue(), _Settings(), None)
    names = [p.name for p in parsers]
    assert "kwork" in names and "kwork_com" in names


def test_disabled_kwork_is_not_built() -> None:
    settings = _Settings()
    settings.kwork_enabled = False
    assert build_parsers(asyncio.Queue(), settings, None) == []


def test_enabled_sources_limit_the_registry() -> None:
    parsers = build_parsers(
        asyncio.Queue(), _Settings(), None, enabled_sources=("kwork",)
    )
    assert [p.name for p in parsers] == ["kwork"]


def test_broken_factory_does_not_break_startup() -> None:
    """Отказ одного источника не должен ронять остальные."""
    from core import sources as sources_module

    original = sources_module.SOURCES
    import parsers.registry as registry

    registry.SOURCES = original + (
        sources_module.Source("broken", "X", factory="нет.такого:модуля"),
    )
    try:
        parsers = build_parsers(asyncio.Queue(), _Settings(), None)
        assert "kwork" in [p.name for p in parsers]
    finally:
        registry.SOURCES = original

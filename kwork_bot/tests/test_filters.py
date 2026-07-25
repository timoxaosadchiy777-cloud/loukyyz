"""Тесты фильтрации лидов (LeadFilter)."""

from __future__ import annotations

from schemas.filters import FilterConfig
from schemas.lead import LeadCreate
from services.filtering import LeadFilter


def _lead(**overrides) -> LeadCreate:
    base = dict(
        source="kwork",
        external_id="1",
        title="Нужен парсер на Python",
        url="https://kwork.ru/projects/view/1",
        description="Собрать данные с сайта",
        budget_raw="5 000 ₽",
        budget_value=5000,
    )
    base.update(overrides)
    return LeadCreate(**base)


def _filter() -> LeadFilter:
    return LeadFilter(FilterConfig(
        keywords=["python", "парсер"],
        stop_words=["за отзыв", "бесплатно"],
        min_budget=1000,
    ))


def test_valid_lead_passes() -> None:
    verdict = _filter().check(_lead())
    assert verdict.passed and verdict.reason == ""


def test_stop_word_rejected() -> None:
    verdict = _filter().check(_lead(description="Сделаю за отзыв"))
    assert not verdict.passed and "стоп-слово" in verdict.reason


def test_missing_keyword_rejected() -> None:
    verdict = _filter().check(_lead(title="Нужен дизайнер логотипа", description="векторный логотип"))
    assert not verdict.passed and "ключев" in verdict.reason


def test_low_budget_rejected() -> None:
    verdict = _filter().check(_lead(budget_value=500))
    assert not verdict.passed and "бюджет" in verdict.reason


def test_unknown_budget_passes() -> None:
    # Бюджет не распознан (None) — по бюджету не отсекаем.
    verdict = _filter().check(_lead(budget_value=None, budget_raw="договорная"))
    assert verdict.passed


def test_no_keywords_config_disables_keyword_filter() -> None:
    lead_filter = LeadFilter(FilterConfig(keywords=[], stop_words=[], min_budget=0))
    assert lead_filter.check(_lead(title="что угодно", description="без ключей")).passed

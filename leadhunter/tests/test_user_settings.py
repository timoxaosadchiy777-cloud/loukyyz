"""Тесты реестра бирж и персональных фильтров."""

from __future__ import annotations

from core.models import Order
from core.runtime_config import ALL_SOURCES as RUNTIME_SOURCES
from core.sources import ALL_SOURCES, SOURCES, get_source, is_available, source_label
from core.user_settings import UserSettings


def _order(**kwargs) -> Order:
    base = dict(
        source="freelancer",
        external_id="1",
        title="Нужен Telegram бот на Python",
        url="https://example.com",
        description="Парсинг сайта и выгрузка в Google Sheets",
    )
    base.update(kwargs)
    return Order(**base)


# --- Реестр бирж ----------------------------------------------------------


def test_all_sources_are_only_available_ones() -> None:
    """Fiverr в реестре есть, но парсить у него нечего — выбрать нельзя."""
    assert "fiverr" not in ALL_SOURCES
    assert {
        "upwork", "kwork", "kwork_com", "freelancer", "peopleperhour", "guru"
    } <= set(ALL_SOURCES)


def test_kwork_is_available_now() -> None:
    """Парсер Kwork реализован — площадка выбирается как обычная."""
    kwork = get_source("kwork")
    assert kwork is not None
    assert kwork.available is True
    assert "нет парсера" not in kwork.button_label
    assert is_available("kwork") is True


def test_source_without_parser_is_marked_in_label() -> None:
    """Механизм «площадка в реестре, но парсера нет» должен работать."""
    from core.sources import Source

    planned = Source("future", "🆕 Новая биржа", available=False)
    assert "нет парсера" in planned.button_label
    assert is_available("future") is False


def test_runtime_config_reuses_same_registry() -> None:
    """settings.yaml валидируется тем же списком — без второго источника правды."""
    assert RUNTIME_SOURCES is ALL_SOURCES


def test_unknown_source_label_falls_back_to_id() -> None:
    assert source_label("нет-такой") == "нет-такой"
    assert get_source("нет-такой") is None


def test_source_ids_are_unique() -> None:
    ids = [s.id for s in SOURCES]
    assert len(ids) == len(set(ids))


# --- Пустые фильтры = без ограничений -------------------------------------


def test_default_settings_match_everything() -> None:
    settings = UserSettings()
    assert settings.matches(_order()) is True
    assert settings.matches(_order(source="freelancer", budget_value=1)) is True


def test_new_user_is_not_onboarded() -> None:
    assert UserSettings().onboarded is False


# --- Биржи ----------------------------------------------------------------


def test_toggle_source_starts_from_all() -> None:
    """Первое выключение трактуется как «все, кроме этой»."""
    settings = UserSettings().toggled_source("kwork")
    assert "kwork" not in settings.sources
    assert settings.source_enabled("kwork") is False
    assert settings.source_enabled("freelancer") is True


def test_toggle_source_back_on() -> None:
    settings = UserSettings(sources=("kwork",)).toggled_source("guru")
    assert settings.sources == ("kwork", "guru")  # порядок из реестра


def test_toggle_unavailable_source_is_ignored() -> None:
    settings = UserSettings().toggled_source("нет-такой-биржи")
    assert settings.sources == ()


def test_order_from_disabled_source_filtered_out() -> None:
    settings = UserSettings(sources=("kwork",))
    assert settings.matches(_order(source="freelancer")) is False


# --- Бюджет ---------------------------------------------------------------


def test_budget_below_threshold_filtered() -> None:
    settings = UserSettings(min_budget=300)
    assert settings.matches(_order(budget_value=100)) is False
    assert settings.matches(_order(budget_value=300)) is True


def test_unknown_budget_passes() -> None:
    """Лид без распознанной суммы не теряем — бюджет часто обсуждается в чате."""
    settings = UserSettings(min_budget=1000)
    assert settings.matches(_order(budget_value=None)) is True


# --- Ключевые слова -------------------------------------------------------


def test_keyword_matches_case_insensitively() -> None:
    settings = UserSettings(keywords=("telegram",))
    assert settings.matches(_order(title="Нужен TELEGRAM бот")) is True


def test_keyword_matches_description_too() -> None:
    settings = UserSettings(keywords=("google sheets",))
    assert settings.matches(_order()) is True


def test_missing_keyword_filters_out() -> None:
    settings = UserSettings(keywords=("wordpress",))
    assert settings.matches(_order()) is False


def test_add_custom_keywords_dedupes_and_lowercases() -> None:
    settings = UserSettings().with_keywords_added("Python, Telegram , python")
    assert settings.keywords == ("python", "telegram")


def test_add_custom_keywords_accepts_newlines() -> None:
    settings = UserSettings().with_keywords_added("парсинг\nбот")
    assert settings.keywords == ("парсинг", "бот")


def test_keywords_are_capped() -> None:
    from core.user_settings import MAX_KEYWORDS

    settings = UserSettings().with_keywords_added(
        ",".join(f"kw{i}" for i in range(MAX_KEYWORDS + 10))
    )
    assert len(settings.keywords) == MAX_KEYWORDS


def test_toggle_keyword_off() -> None:
    settings = UserSettings(keywords=("python", "bot")).toggled_keyword("python")
    assert settings.keywords == ("bot",)


# --- Категории ------------------------------------------------------------


def test_category_matches_by_substring_both_ways() -> None:
    """Категория от ИИ — свободный текст, точного совпадения ждать нельзя."""
    settings = UserSettings(categories=("Telegram-боты",))
    assert settings.category_matches("Telegram-боты и автоматизация") is True
    assert settings.category_matches("Вёрстка") is False


def test_empty_category_filtered_when_categories_chosen() -> None:
    settings = UserSettings(categories=("AI и LLM",))
    assert settings.matches(_order(category="")) is False


def test_toggle_category() -> None:
    settings = UserSettings().toggled_category("AI и LLM")
    assert settings.categories == ("AI и LLM",)
    assert settings.toggled_category("AI и LLM").categories == ()


# --- Сводка для экрана настроек -------------------------------------------


def test_summary_reports_defaults_as_unrestricted() -> None:
    lines = "\n".join(UserSettings().summary_lines())
    assert "все доступные" in lines
    assert "любые" in lines
    assert "без ограничения" in lines

"""Персональные фильтры пользователя.

У каждого `telegram_id` — свой набор фильтров, хранится в таблице
``user_settings``. Глобальный ``settings.yaml`` остаётся эксплуатационными
«крутилками» владельца (min_score, LLM) и пользовательских фильтров не задаёт.

Пустой список везде означает «без ограничения»: так новый пользователь, ничего
не выбравший в мастере, получает лиды, а не тишину.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from core.models import Order
from core.sources import ALL_SOURCES, is_available

# --- Пресеты для мастера онбординга ---------------------------------------
# Переключаются по ИНДЕКСУ в этих кортежах: у Telegram лимит 64 байта на
# callback_data, а кириллица в UTF-8 его быстро пробивает. Порядок менять
# безопасно — индексы живут только внутри одного экрана.

CATEGORIES: tuple[str, ...] = (
    "Telegram-боты",
    "Парсинг и скрапинг",
    "Автоматизация",
    "API и интеграции",
    "Веб-разработка",
    "Скрипты и утилиты",
    "AI и LLM",
    "Базы данных",
)

KEYWORD_PRESETS: tuple[str, ...] = (
    "python",
    "telegram",
    "bot",
    "aiogram",
    "parsing",
    "scraping",
    "api",
    "automation",
    "django",
    "fastapi",
    "sql",
    "ai",
)

BUDGET_PRESETS: tuple[int, ...] = (0, 50, 100, 300, 500, 1000)

# Сколько своих ключевых слов разрешаем — защита от гигантского фильтра.
MAX_KEYWORDS = 30


@dataclass(frozen=True, slots=True)
class UserSettings:
    """Снимок персональных фильтров.

    Attributes:
        sources: Выбранные биржи. Пустой кортеж = все доступные.
        categories: Интересующие категории. Пустой = любые.
        keywords: Ключевые слова (регистронезависимо). Пустой = любые.
        min_budget: Минимальный бюджет в USD. Лид без распознанной суммы проходит.
        onboarded: Прошёл ли пользователь мастер настройки.
    """

    sources: tuple[str, ...] = field(default_factory=tuple)
    categories: tuple[str, ...] = field(default_factory=tuple)
    keywords: tuple[str, ...] = field(default_factory=tuple)
    min_budget: int = 0
    onboarded: bool = False
    # True — список бирж пришёл из sources_settings и уже учитывает дефолты
    # реестра. Тогда пустой список значит «выключено всё», а не «включено всё».
    sources_explicit: bool = False

    # --- Предикаты фильтрации ---------------------------------------------

    def source_enabled(self, source: str) -> bool:
        """Разрешена ли биржа.

        Пустой список означает «все» только когда выбор ещё не загружен из
        sources_settings: там пустой список — это осознанно выключенные биржи.
        """
        if not self.sources and not self.sources_explicit:
            return True
        return source in self.sources

    def category_matches(self, category: str) -> bool:
        """Категория от ИИ — свободный текст, поэтому сверяем по вхождению."""
        if not self.categories:
            return True
        if not category:
            return False
        needle = category.casefold()
        return any(
            chosen.casefold() in needle or needle in chosen.casefold()
            for chosen in self.categories
        )

    def keyword_matches(self, text: str) -> bool:
        if not self.keywords:
            return True
        haystack = text.casefold()
        return any(word.casefold() in haystack for word in self.keywords)

    def technology_matches(self, technology: str) -> bool:
        """Стек от ИИ — дополнительный шанс совпасть по ключевым словам."""
        if not self.keywords or not technology:
            return False
        return self.keyword_matches(technology)

    def budget_matches(self, budget_value: int | None) -> bool:
        # Лид без распознанной суммы не отсекаем — иначе теряем хорошие заказы,
        # где бюджет обсуждается в переписке.
        if budget_value is None:
            return True
        return budget_value >= self.min_budget

    def prematches(self, order: Order) -> bool:
        """Дешёвый предфильтр ДО обращения к ИИ (см. :mod:`core.fanout`).

        Проверяет только то, что известно из сырого лида: биржу, бюджет и
        ключевые слова в заголовке/описании. Категорию здесь проверить нельзя —
        её ещё не определил ИИ, поэтому на этой стадии она не ограничивает.
        """
        return (
            self.source_enabled(order.source)
            and self.budget_matches(order.budget_value)
            and self.keyword_matches(f"{order.title}\n{order.description}")
        )

    def matches(self, order: Order) -> bool:
        """Полный фильтр: предфильтр плюс признаки, добытые ИИ.

        Ключевые слова могут совпасть либо с текстом заказа, либо со стеком,
        который распознал ИИ («python» в technology при описании без этого слова).
        """
        if not (
            self.source_enabled(order.source)
            and self.budget_matches(order.budget_value)
            and self.category_matches(order.category)
        ):
            return False
        return self.keyword_matches(
            f"{order.title}\n{order.description}"
        ) or self.technology_matches(order.technology)

    # --- Изменение (dataclass frozen → возвращаем новый объект) ------------

    def toggled_source(self, source_id: str) -> UserSettings:
        """Включает/выключает биржу. Недоступные площадки игнорируются."""
        if not is_available(source_id):
            return self
        current = set(self.sources or ALL_SOURCES)
        if source_id in current:
            current.discard(source_id)
        else:
            current.add(source_id)
        # Порядок держим как в реестре — так экран не «прыгает».
        ordered = tuple(s for s in ALL_SOURCES if s in current)
        return self.replace(sources=ordered)

    def toggled_category(self, category: str) -> UserSettings:
        return self.replace(categories=_toggle(self.categories, category))

    def toggled_keyword(self, keyword: str) -> UserSettings:
        return self.replace(keywords=_toggle(self.keywords, keyword.casefold()))

    def with_keywords_added(self, raw: str) -> UserSettings:
        """Добавляет свои ключевые слова из строки «a, b, c»."""
        added = list(self.keywords)
        for chunk in raw.replace("\n", ",").split(","):
            word = chunk.strip().casefold()
            if word and word not in added and len(added) < MAX_KEYWORDS:
                added.append(word)
        return self.replace(keywords=tuple(added))

    def replace(self, **changes) -> UserSettings:
        data = {
            "sources": self.sources,
            "categories": self.categories,
            "keywords": self.keywords,
            "min_budget": self.min_budget,
            "onboarded": self.onboarded,
            "sources_explicit": self.sources_explicit,
        }
        data.update(changes)
        return UserSettings(**data)

    # --- Представление для экрана настроек --------------------------------

    def summary_lines(self) -> list[str]:
        from core.sources import source_label

        sources = (
            ", ".join(source_label(s) for s in self.sources)
            if self.sources
            else "все доступные"
        )
        return [
            f"🌐 Биржи: {sources}",
            f"🏷 Категории: {', '.join(self.categories) or 'любые'}",
            f"🔑 Ключевые слова: {', '.join(self.keywords) or 'любые'}",
            f"💰 Минимальный бюджет: {self.min_budget}$"
            if self.min_budget
            else "💰 Минимальный бюджет: без ограничения",
        ]


def _toggle(values: tuple[str, ...], value: str) -> tuple[str, ...]:
    if value in values:
        return tuple(v for v in values if v != value)
    return values + (value,)

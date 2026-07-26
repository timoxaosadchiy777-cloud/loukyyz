"""Реестр бирж (источников лидов).

Единственное место, где перечислены площадки. Чтобы добавить новую биржу:

  1. добавить строку в :data:`SOURCES`;
  2. написать парсер в ``parsers/`` (см. ``parsers/base.py``).

UI бота, пользовательские фильтры и валидация ``settings.yaml`` подхватят её
автоматически — списки нигде не дублируются.

Площадка с ``available=False`` показывается в интерфейсе как «скоро»: включить
её нельзя, пока нет парсера. Так Kwork занимает своё место в UI заранее.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Source:
    """Описание биржи.

    Attributes:
        id: Идентификатор источника — совпадает с ``Order.source``.
        label: Человекочитаемое название для кнопок и экранов.
        available: Есть ли рабочий парсер. ``False`` → «скоро», выбрать нельзя.
    """

    id: str
    label: str
    available: bool = True

    @property
    def button_label(self) -> str:
        return self.label if self.available else f"{self.label} (скоро)"


SOURCES: tuple[Source, ...] = (
    Source("upwork", "💼 Upwork"),
    Source("fiverr", "🛒 Fiverr"),
    Source("rss", "🌐 RSS / джоб-борды"),
    # Фаза 4: нужен Playwright и залогиненная сессия — парсера пока нет.
    Source("kwork", "🇷🇺 Kwork", available=False),
)

# Источники с рабочим парсером. Именно они допустимы в settings.yaml и в
# пользовательских фильтрах.
ALL_SOURCES: tuple[str, ...] = tuple(s.id for s in SOURCES if s.available)


def get_source(source_id: str) -> Source | None:
    for source in SOURCES:
        if source.id == source_id:
            return source
    return None


def source_label(source_id: str) -> str:
    """Название биржи для интерфейса; для неизвестного id — сам id."""
    source = get_source(source_id)
    return source.label if source else source_id


def is_available(source_id: str) -> bool:
    source = get_source(source_id)
    return bool(source and source.available)

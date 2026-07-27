"""Реестр бирж (источников лидов).

Единственное место, где перечислены площадки. Чтобы добавить новую биржу:

  1. добавить строку в :data:`SOURCES`;
  2. написать парсер в ``parsers/`` (см. ``parsers/base.py``).

UI бота, пользовательские фильтры и валидация ``settings.yaml`` подхватят её
автоматически — списки нигде не дублируются.

Площадка с ``available=False`` показывается в интерфейсе красным: включить её
нельзя, потому что парсера нет. Так пользователь видит полный список бирж и
понимает, чего ждать, а чего — нет.
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
        factory: Путь к фабрике парсера — ``"модуль:функция"``. Импортируется
            лениво, поэтому тяжёлые зависимости источника не тянутся, пока он
            не понадобился. Пустая строка = источник без собственного парсера.
        default_enabled: Включена ли биржа у нового пользователя.
        note: Пояснение для владельца — почему биржа выключена или чем особенна.
        needs: Переменная окружения, без которой парсер не поднимется. Экран
            «Биржи» подсказывает её, если биржа включена, а опрос не идёт.
    """

    id: str
    label: str
    available: bool = True
    factory: str = ""
    default_enabled: bool = True
    note: str = ""
    needs: str = ""

    @property
    def button_label(self) -> str:
        return self.label if self.available else f"{self.label} (нет парсера)"


# Подключить новую биржу = добавить строку сюда и написать фабрику
# `build(queue, settings, alerter, source) -> BaseParser | None`.
# Всё остальное — мастер настройки, фильтры, меню «Биржи», валидация
# settings.yaml — подхватит её автоматически.
SOURCES: tuple[Source, ...] = (
    # --- Биржи с собственным парсером ---
    # Порядок здесь = порядок кнопок на экране «Биржи».
    Source(
        "upwork", "💼 Upwork",
        factory="parsers.upwork_parser:build",
        needs="UPWORK_RSS_URL",
        note="лента сохранённого поиска: скопируйте её RSS-ссылку в UPWORK_RSS_URL",
    ),
    Source(
        "kwork", "🇷🇺 Kwork.ru",
        factory="parsers.kwork_parser:build",
        needs="KWORK_ENABLED",
    ),
    Source(
        "kwork_com", "🌍 Kwork.com",
        factory="parsers.kwork_parser:build",
        needs="KWORK_ENABLED",
    ),
    Source(
        "freelancer", "🌐 Freelancer.com",
        factory="parsers.freelancer_parser:build",
    ),
    Source(
        "peopleperhour", "🇬🇧 PeoplePerHour",
        factory="parsers.pph_parser:build",
    ),
    Source(
        "guru", "🎯 Guru.com",
        factory="parsers.guru_parser:build",
    ),

    # --- RSS: вспомогательный источник, а не основной ---
    # По умолчанию выключен: лента отдаёт вакансии в штат, а не заказы, и
    # забивает выдачу. Включается осознанно.
    Source(
        "weworkremotely", "📰 WeWorkRemotely (RSS)",
        factory="parsers.rss_parser:build",
        default_enabled=False,
        note="джоб-борд: вакансии в штат, не разовые заказы",
    ),

    # --- Площадки без публичного доступа к заказам ---
    # Не заглушка: парсера нет, потому что парсить нечего.
    Source(
        "fiverr", "🛒 Fiverr", available=False,
        note="витрина гигов; раздел Buyer Requests закрыт в 2023",
    ),
)


def default_enabled_ids() -> tuple[str, ...]:
    """Источники, включённые у нового пользователя по умолчанию."""
    return tuple(s.id for s in SOURCES if s.available and s.default_enabled)

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

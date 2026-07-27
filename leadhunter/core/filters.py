"""Парсинг и нормализация бюджета.

Фильтрация по ключевым словам и стоп-фразам убрана в LeadHunter 2.0: решение о
релевантности принимает ИИ (см. :mod:`ai.scoring`). Здесь остаётся разбор суммы
бюджета — дешёвый предварительный фильтр ДО обращения к LLM.

**Валюта.** Порог ``min_budget`` пользователь задаёт в долларах, а площадки
отдают суммы в разных валютах: Upwork в USD, Kwork в рублях. Поэтому
``Order.budget_value`` хранит сумму, ПРИВЕДЁННУЮ к USD, а исходная строка
остаётся в ``budget_raw`` и показывается в карточке как есть. Без этого заказ
на 5 000 ₽ сравнивался бы с порогом как 5000 долларов.
"""

from __future__ import annotations

import re

# Первое «число» в строке: допускаем пробелы/точки/запятые как разделители разрядов.
_NUMBER_RE = re.compile(r"\d[\d\s.,]*")

USD = "USD"
RUB = "RUB"

# Символы и коды валют, встречающиеся в текстах заказов.
_CURRENCY_MARKERS: tuple[tuple[str, str], ...] = (
    ("₽", RUB),
    ("руб", RUB),
    ("rub", RUB),
    ("р.", RUB),
    ("$", USD),
    ("usd", USD),
)


def detect_currency(text: str | None, default: str = USD) -> str:
    """Определяет валюту по строке бюджета («5 000 ₽» → RUB, «$100» → USD)."""
    if not text:
        return default
    lowered = text.casefold()
    for marker, currency in _CURRENCY_MARKERS:
        if marker in lowered:
            return currency
    return default


def parse_budget(text: str | None) -> int | None:
    """Извлекает числовой бюджет из произвольного текста.

    Примеры: ``"5 000 ₽"`` → 5000, ``"$100"`` → 100, ``"договорная"`` → ``None``.
    Валюту не учитывает — для сравнения с порогом используйте :func:`to_usd`.
    """
    if not text:
        return None
    match = _NUMBER_RE.search(text.replace("\xa0", " "))
    if not match:
        return None
    digits = re.sub(r"\D", "", match.group(0))
    return int(digits) if digits else None


def to_usd(value: int | None, currency: str, *, usd_rub_rate: float) -> int | None:
    """Приводит сумму к долларам для сравнения с порогом пользователя.

    Курс приблизительный и настраивается (``USD_RUB_RATE``): он нужен только
    для отсечки по порогу, а не для расчётов с деньгами. В карточке всегда
    показывается исходная строка бюджета.
    """
    if value is None:
        return None
    if currency == RUB and usd_rub_rate > 0:
        return int(round(value / usd_rub_rate))
    return value


def parse_budget(text: str | None) -> int | None:
    """Извлекает числовой бюджет из произвольного текста.

    Примеры: ``"5 000 ₽"`` → 5000, ``"$100"`` → 100, ``"договорная"`` → ``None``.
    """
    if not text:
        return None
    match = _NUMBER_RE.search(text.replace("\xa0", " "))
    if not match:
        return None
    digits = re.sub(r"\D", "", match.group(0))
    return int(digits) if digits else None

"""Парсинг бюджета.

Фильтрация по ключевым словам и стоп-фразам убрана в LeadHunter 2.0: решение о
релевантности принимает ИИ (см. :mod:`ai.scoring`). Здесь остаётся только разбор
суммы бюджета — он нужен как дешёвый предварительный фильтр ДО обращения к LLM.
"""

from __future__ import annotations

import re

# Первое «число» в строке: допускаем пробелы/точки/запятые как разделители разрядов.
_NUMBER_RE = re.compile(r"\d[\d\s.,]*")


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

"""Фильтрация мусора и парсинг бюджета."""

from __future__ import annotations

import re

from core.models import Order

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


def is_junk(
    order: Order,
    *,
    min_budget: int,
    junk_phrases: list[str],
) -> tuple[bool, str]:
    """Проверяет, является ли заказ мусором.

    Returns:
        Кортеж ``(is_junk, reason)``. ``reason`` пуст, если заказ валиден.
    """
    haystack = f"{order.title}\n{order.description}".lower()

    for phrase in junk_phrases:
        if phrase and phrase.lower() in haystack:
            return True, f"стоп-фраза: {phrase!r}"

    if order.budget_value is not None and order.budget_value < min_budget:
        return True, f"низкий бюджет: {order.budget_value} < {min_budget}"

    return False, ""

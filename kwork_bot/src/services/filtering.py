"""Правила фильтрации заказов (чистая, легко тестируемая логика)."""

from __future__ import annotations

from dataclasses import dataclass

from schemas.filters import FilterConfig
from schemas.lead import LeadCreate


@dataclass(slots=True)
class FilterVerdict:
    """Результат проверки заказа фильтрами."""

    passed: bool
    reason: str = ""


class LeadFilter:
    """Применяет стоп-слова, ключевые слова и минимальный бюджет."""

    def __init__(self, config: FilterConfig) -> None:
        self._stop_words = [w.lower() for w in config.stop_words]
        self._keywords = [w.lower() for w in config.keywords]
        self._min_budget = config.min_budget

    def check(self, lead: LeadCreate) -> FilterVerdict:
        haystack = f"{lead.title}\n{lead.description}".lower()

        for word in self._stop_words:
            if word and word in haystack:
                return FilterVerdict(False, f"стоп-слово: {word!r}")

        if self._keywords and not any(kw in haystack for kw in self._keywords):
            return FilterVerdict(False, "нет ни одного ключевого слова")

        if lead.budget_value is not None and lead.budget_value < self._min_budget:
            return FilterVerdict(False, f"бюджет {lead.budget_value} < {self._min_budget}")

        return FilterVerdict(True)

"""Решающий слой пайплайна: перенос оценки в заказ и решение о доставке.

Вынесено из ``main.py`` отдельным модулем, чтобы логику решения можно было
тестировать без зависимостей парсера/бота.
"""

from __future__ import annotations

from ai.scoring import LeadScore
from core.models import Order


def apply_score(order: Order, lead_score: LeadScore) -> None:
    """Переносит результат скоринга в модель заказа (для БД и карточки)."""
    order.score = lead_score.score
    order.category = lead_score.category
    order.reason = lead_score.reason
    order.should_send = lead_score.should_send


def decide(lead_score: LeadScore, *, min_score: int) -> bool | None:
    """Решение о доставке заказа.

    Returns:
        ``True``  — заказ проходит (ИИ рекомендует и score ≥ порога);
        ``False`` — заказ отклонён ИИ (низкий score или явный веток should_send);
        ``None``  — ИИ недоступен, решение принять нельзя (fail-open с пометкой).
    """
    if not lead_score.available:
        return None
    # Явный веток от ИИ (should_send=false) отклоняет заказ независимо от score.
    if lead_score.should_send is False:
        return False
    return (lead_score.score or 0) >= min_score

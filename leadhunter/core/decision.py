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
    order.probability_of_sale = lead_score.probability_of_sale
    order.should_send = lead_score.should_send
    order.technology = lead_score.technology
    order.summary = lead_score.summary


# Выше этой оценки веток модели считается противоречием и не применяется.
#
# should_send задуман как предохранитель от очевидного мусора, но модели
# охотно ставят false «на всякий случай» — и тогда веток превращался в
# невидимый второй фильтр: при min_score=0 заказ с приличной оценкой всё равно
# отклонялся, и владелец не понимал, почему настройка не работает.
# Если модель сама оценила заказ достаточно высоко, доверяем числу, а не флагу.
VETO_SCORE_CEILING = 50


def decide(lead_score: LeadScore, *, min_score: int) -> bool | None:
    """Решение о доставке заказа.

    Returns:
        ``True``  — заказ проходит (score ≥ порога и нет осмысленного ветка);
        ``False`` — заказ отклонён (низкий score либо веток на низкой оценке);
        ``None``  — ИИ недоступен, решение принять нельзя (fail-open с пометкой).
    """
    if not lead_score.available:
        return None

    score = lead_score.score or 0
    # Веток уважаем только там, где он согласуется с оценкой: «не показывать»
    # при score=70 — это противоречие в ответе модели, а не решение.
    if lead_score.should_send is False and score < VETO_SCORE_CEILING:
        return False
    return score >= min_score

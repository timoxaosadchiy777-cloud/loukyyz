"""Подбор получателей лида (fan-out).

Один лид → много пользователей, но ИИ вызывается ОДИН раз на лид, а не на
каждого получателя. Достигается двумя стадиями отбора вокруг единственного
AI-анализа::

    лид → prefilter() → [если пусто: ИИ не вызывается вообще]
        → один AI-анализ (категория, стек, суть)
        → select() → [если пусто: отклик не генерируется]
        → один отклик → рассылка

Стадия 1 знает только сырой лид (биржа, бюджет, слова в тексте), стадия 2 —
ещё и признаки от ИИ. Обе стадии чистые и не ходят в сеть.
"""

from __future__ import annotations

from dataclasses import dataclass

from core.models import Order
from core.user_settings import UserSettings


@dataclass(frozen=True, slots=True)
class Recipient:
    """Пользователь-получатель вместе с его персональными фильтрами."""

    telegram_id: int
    settings: UserSettings


def prefilter(recipients: list[Recipient], order: Order) -> list[Recipient]:
    """Стадия 1: кому лид потенциально интересен — без единого вызова ИИ.

    Пустой результат означает, что анализировать лид незачем: он не нужен
    никому. Это главная экономия — мусорные лиды не стоят ни одного запроса.
    """
    return [r for r in recipients if r.settings.prematches(order)]


def select(recipients: list[Recipient], order: Order) -> list[Recipient]:
    """Стадия 2: кому лид отправляем — с учётом категории и стека от ИИ."""
    return [r for r in recipients if r.settings.matches(order)]

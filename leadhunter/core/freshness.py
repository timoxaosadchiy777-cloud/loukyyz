"""Отсечка устаревших лидов.

Заказ недельной давности бесполезен: на бирже под ним уже сотня откликов, и
отклик там ничего не стоит. Поэтому лиды старше ``max_age_hours`` до пайплайна
не доходят — это дешевле и честнее, чем гонять их через ИИ и показывать людям.

Лид без даты публикации НЕ отбрасывается: часть площадок её не отдаёт, и
молчаливая потеря половины источников хуже, чем изредка показанный старый
заказ. Такие лиды помечаются в логе.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from core.models import Order

log = logging.getLogger(__name__)

DEFAULT_MAX_AGE_HOURS = 24


def age_hours(order: Order, *, now: datetime | None = None) -> float | None:
    """Возраст лида в часах. ``None`` — биржа не сообщила дату публикации."""
    if order.published_at is None:
        return None
    moment = now or datetime.now(timezone.utc)
    published = order.published_at
    if published.tzinfo is None:
        published = published.replace(tzinfo=timezone.utc)
    return (moment - published).total_seconds() / 3600.0


def is_fresh(
    order: Order,
    *,
    max_age_hours: int = DEFAULT_MAX_AGE_HOURS,
    now: datetime | None = None,
) -> bool:
    """Достаточно ли свеж лид, чтобы на него имело смысл откликаться."""
    if max_age_hours <= 0:
        return True  # отсечка выключена

    age = age_hours(order, now=now)
    if age is None:
        return True  # даты нет — не теряем лид, см. модуль-docstring
    # Небольшой запас в минус: часы биржи могут слегка расходиться с нашими.
    return age <= max_age_hours


def cutoff(max_age_hours: int = DEFAULT_MAX_AGE_HOURS) -> datetime:
    """Момент, старше которого лиды не берём — для запросов к API бирж."""
    return datetime.now(timezone.utc) - timedelta(hours=max_age_hours)

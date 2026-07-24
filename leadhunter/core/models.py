"""Доменные модели LeadHunter."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(slots=True)
class Order:
    """Единая карточка лида из любого источника.

    Attributes:
        source: Источник лида — ``"upwork"`` / ``"fiverr"`` / ``"rss"``.
        external_id: Уникальный идентификатор в рамках источника (для дедупликации).
        title: Короткий заголовок вакансии/проекта.
        url: Прямая ссылка на лид.
        description: Текст вакансии/ТЗ.
        budget_raw: Бюджет в исходном виде («$150», …).
        budget_value: Распарсенный числовой бюджет в USD (или ``None``).
        created_at: Момент обнаружения лида.
    """

    source: str
    external_id: str
    title: str
    url: str
    description: str
    budget_raw: str = ""
    budget_value: int | None = None
    created_at: datetime = field(default_factory=_utcnow)

    @property
    def dedup_key(self) -> str:
        """Глобально уникальный ключ заказа."""
        return f"{self.source}:{self.external_id}"

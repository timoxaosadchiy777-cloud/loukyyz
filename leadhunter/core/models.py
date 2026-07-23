"""Доменные модели LeadHunter."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(slots=True)
class Order:
    """Единая карточка заказа из любого источника.

    Attributes:
        source: Источник заказа — ``"telegram"`` или ``"kwork"``.
        external_id: Уникальный идентификатор в рамках источника (для дедупликации).
        title: Короткий заголовок заказа.
        url: Прямая ссылка на заказ/сообщение.
        description: Полный текст ТЗ.
        budget_raw: Бюджет в исходном виде («5 000 ₽», «договорная», …).
        budget_value: Распарсенный числовой бюджет (или ``None``).
        created_at: Момент обнаружения заказа.
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

"""Доменные модели LeadHunter."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Mapping


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class CrmStatus:
    """Статусы воронки продаж (CRM). Хранятся в БД строкой."""

    NEW = "new"
    CONTACTED = "contacted"
    NEGOTIATION = "negotiation"
    WON = "won"
    LOST = "lost"

    ALL = (NEW, CONTACTED, NEGOTIATION, WON, LOST)


# Человеко-читаемые подписи статусов (для карточки и кнопок).
CRM_LABELS: dict[str, str] = {
    CrmStatus.NEW: "🆕 Новый",
    CrmStatus.CONTACTED: "✉️ Написал",
    CrmStatus.NEGOTIATION: "💬 Переговоры",
    CrmStatus.WON: "✅ Выиграл",
    CrmStatus.LOST: "❌ Проиграл",
}


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
        score: AI Score 0..100 (или ``None``, если ИИ недоступен).
        category: Категория заказа по мнению ИИ.
        reason: Обоснование оценки от ИИ.
        should_send: Рекомендация ИИ показывать ли заказ (или ``None``).
        crm_status: Статус воронки (см. :class:`CrmStatus`).
    """

    source: str
    external_id: str
    title: str
    url: str
    description: str
    budget_raw: str = ""
    budget_value: int | None = None
    created_at: datetime = field(default_factory=_utcnow)
    # --- AI Lead Scoring ---
    score: int | None = None
    category: str = ""
    reason: str = ""
    probability_of_sale: int | None = None
    should_send: bool | None = None
    # --- CRM ---
    crm_status: str = CrmStatus.NEW

    @property
    def dedup_key(self) -> str:
        """Глобально уникальный ключ заказа."""
        return f"{self.source}:{self.external_id}"

    @classmethod
    def from_row(cls, row: Mapping) -> Order:
        """Восстанавливает Order из строки БД (для перерисовки карточки).

        Дата/время в модели не участвует в отрисовке карточки, поэтому берём
        текущий момент — исходный created_at остаётся в БД как есть.
        """
        should_send = row["should_send"]
        return cls(
            source=row["source"],
            external_id=row["external_id"],
            title=row["title"],
            url=row["url"],
            description=row["description"],
            budget_raw=row["budget_raw"] or "",
            budget_value=row["budget_value"],
            score=row["score"],
            category=row["category"] or "",
            reason=row["reason"] or "",
            probability_of_sale=row["probability_of_sale"],
            should_send=None if should_send is None else bool(should_send),
            crm_status=row["crm_status"] or CrmStatus.NEW,
        )

"""Фабрики callback-данных инлайн-кнопок."""

from __future__ import annotations

from aiogram.filters.callback_data import CallbackData


class LeadCB(CallbackData, prefix="lead"):
    """Действие над заказом: ``refresh`` (обновить отклик) или ``copy`` (скопировать)."""

    action: str
    lead_id: int

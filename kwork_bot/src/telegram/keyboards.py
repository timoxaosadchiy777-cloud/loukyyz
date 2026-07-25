"""Инлайн-клавиатуры карточек заказов."""

from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from telegram.callbacks import LeadCB


def lead_keyboard(lead_id: int, url: str) -> InlineKeyboardMarkup:
    """Кнопки: открыть заказ, обновить отклик, скопировать отклик."""
    builder = InlineKeyboardBuilder()
    builder.button(text="🔗 Открыть заказ", url=url)
    builder.button(text="🔄 Обновить отклик", callback_data=LeadCB(action="refresh", lead_id=lead_id))
    builder.button(text="📋 Скопировать отклик", callback_data=LeadCB(action="copy", lead_id=lead_id))
    builder.adjust(1)
    return builder.as_markup()

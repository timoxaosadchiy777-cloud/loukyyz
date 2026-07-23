"""Инлайн-клавиатуры бота."""

from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.callbacks import OrderAction


def order_keyboard(order_id: int) -> InlineKeyboardMarkup:
    """Клавиатура под карточкой заказа: принять или скипнуть."""
    builder = InlineKeyboardBuilder()
    builder.button(
        text="🚀 Скопировать / Отправить",
        callback_data=OrderAction(action="accept", order_id=order_id),
    )
    builder.button(
        text="❌ Скипнуть",
        callback_data=OrderAction(action="skip", order_id=order_id),
    )
    builder.adjust(1)
    return builder.as_markup()

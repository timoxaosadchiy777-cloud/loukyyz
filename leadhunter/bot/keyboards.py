"""Инлайн-клавиатуры бота."""

from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.callbacks import CrmAction, OrderAction
from core.models import CRM_LABELS, CrmStatus

# Порядок кнопок воронки под карточкой (NEW — стартовый статус, кнопки нет).
_CRM_FLOW = (
    CrmStatus.CONTACTED,
    CrmStatus.NEGOTIATION,
    CrmStatus.WON,
    CrmStatus.LOST,
)


def order_keyboard(order_id: int, crm_status: str = CrmStatus.NEW) -> InlineKeyboardMarkup:
    """Клавиатура под карточкой: копирование отклика + управление воронкой CRM.

    Текущий статус помечается точкой и не дублируется отдельной кнопкой.
    """
    builder = InlineKeyboardBuilder()
    builder.button(
        text="📋 Скопировать отклик",
        callback_data=OrderAction(action="copy", order_id=order_id),
    )
    for status in _CRM_FLOW:
        label = CRM_LABELS[status]
        if status == crm_status:
            label = f"• {label}"
        builder.button(
            text=label,
            callback_data=CrmAction(status=status, order_id=order_id),
        )
    # 1 кнопка копирования сверху, затем воронка по 2 в ряд.
    builder.adjust(1, 2, 2)
    return builder.as_markup()

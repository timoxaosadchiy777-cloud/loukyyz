"""Фабрика callback-данных для инлайн-кнопок."""

from __future__ import annotations

from aiogram.filters.callback_data import CallbackData


class OrderAction(CallbackData, prefix="ord"):
    """Действие над заказом из инлайн-кнопки.

    action: ``"accept"`` (скопировать/отправить) или ``"skip"`` (скипнуть).
    order_id: id заказа в БД.
    """

    action: str
    order_id: int

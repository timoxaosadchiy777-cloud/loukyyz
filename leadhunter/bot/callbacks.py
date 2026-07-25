"""Фабрики callback-данных для инлайн-кнопок."""

from __future__ import annotations

from aiogram.filters.callback_data import CallbackData


class OrderAction(CallbackData, prefix="ord"):
    """Действие над заказом (не меняющее воронку).

    action: ``"copy"`` — прислать чистый текст отклика для копирования/отправки.
    order_id: id заказа в БД.
    """

    action: str
    order_id: int


class CrmAction(CallbackData, prefix="crm"):
    """Смена статуса воронки продаж (CRM).

    status: целевой статус — см. :class:`core.models.CrmStatus`.
    order_id: id заказа в БД.
    """

    status: str
    order_id: int

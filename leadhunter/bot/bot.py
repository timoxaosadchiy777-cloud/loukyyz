"""Сборка бота, роутер и обработчики инлайн-кнопок."""

from __future__ import annotations

import logging

from aiogram import Bot, Dispatcher, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart
from aiogram.types import CallbackQuery, LinkPreviewOptions, Message

from bot.callbacks import CrmAction, OrderAction
from bot.cards import render_card
from bot.keyboards import order_keyboard
from config import Settings
from core.models import CRM_LABELS, CrmStatus, Order
from database.db import Database

log = logging.getLogger(__name__)

router = Router(name="leadhunter")

_NO_PREVIEW = LinkPreviewOptions(is_disabled=True)


def _is_owner(user_id: int | None, owner_id: int) -> bool:
    # owner_id == 0 → фильтр не настроен, пропускаем всех (dev-режим).
    return owner_id == 0 or user_id == owner_id


@router.message(CommandStart())
async def on_start(message: Message, owner_id: int) -> None:
    if not _is_owner(message.from_user.id if message.from_user else None, owner_id):
        return
    await message.answer(
        "👋 <b>LeadHunter</b> на связи.\n"
        "Сюда прилетают карточки заказов с AI-оценкой и готовым откликом.\n"
        "Кнопки под карточкой ведут заказ по воронке: Написал → Переговоры → "
        "Выиграл/Проиграл.\n\n"
        f"Твой user id: <code>{message.from_user.id}</code>"
    )


@router.callback_query(OrderAction.filter())
async def on_order_action(
    query: CallbackQuery,
    callback_data: OrderAction,
    db: Database,
    owner_id: int,
) -> None:
    if not _is_owner(query.from_user.id, owner_id):
        await query.answer("Недоступно", show_alert=True)
        return

    row = await db.get_order(callback_data.order_id)
    if row is None:
        await query.answer("Заказ не найден", show_alert=True)
        return

    if callback_data.action == "copy":
        response = row["response"] or "(отклик отсутствует)"
        if isinstance(query.message, Message):
            # Чистый текст отдельным сообщением — удобно копировать/пересылать.
            await query.message.answer(response, parse_mode=None)
        await query.answer("Отклик готов — копируй и отправляй 🚀")
        return

    await query.answer()


@router.callback_query(CrmAction.filter())
async def on_crm_action(
    query: CallbackQuery,
    callback_data: CrmAction,
    db: Database,
    owner_id: int,
) -> None:
    if not _is_owner(query.from_user.id, owner_id):
        await query.answer("Недоступно", show_alert=True)
        return

    status = callback_data.status
    if status not in CrmStatus.ALL:
        await query.answer("Неизвестный статус", show_alert=True)
        return

    await db.set_crm_status(callback_data.order_id, status)
    row = await db.get_order(callback_data.order_id)
    if row is None:
        await query.answer("Заказ не найден", show_alert=True)
        return

    # Перерисовываем карточку с новым статусом воронки.
    order = Order.from_row(row)
    response = row["response"] or "(отклик отсутствует)"
    if isinstance(query.message, Message):
        try:
            await query.message.edit_text(
                render_card(order, response),
                reply_markup=order_keyboard(callback_data.order_id, status),
                link_preview_options=_NO_PREVIEW,
            )
        except Exception:
            # Повторное нажатие того же статуса → «message is not modified».
            log.debug("Карточка %s не изменилась", callback_data.order_id)
    await query.answer(f"Статус: {CRM_LABELS.get(status, status)}")


def create_bot(settings: Settings) -> Bot:
    return Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )


def create_dispatcher(db: Database, settings: Settings) -> Dispatcher:
    dp = Dispatcher()
    # Зависимости прокидываются в хендлеры по имени аргумента.
    dp["db"] = db
    dp["owner_id"] = settings.owner_id
    dp.include_router(router)
    return dp


async def push_card(
    bot: Bot,
    owner_id: int,
    order: Order,
    response: str,
    order_id: int,
) -> None:
    """Отправляет карточку заказа владельцу."""
    await bot.send_message(
        owner_id,
        render_card(order, response),
        reply_markup=order_keyboard(order_id, order.crm_status),
        link_preview_options=_NO_PREVIEW,
    )

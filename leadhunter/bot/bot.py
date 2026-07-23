"""Сборка бота, роутер и обработчики инлайн-кнопок."""

from __future__ import annotations

import logging

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart
from aiogram.types import CallbackQuery, LinkPreviewOptions, Message

from bot.callbacks import OrderAction
from bot.cards import render_card
from bot.keyboards import order_keyboard
from config import Settings
from core.models import Order
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
        "Сюда будут прилетать карточки свежих заказов с готовыми откликами.\n\n"
        f"Твой user id: <code>{message.from_user.id}</code>"
    )


@router.callback_query(OrderAction.filter(F.action == "accept"))
async def on_accept(
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

    await db.set_status(callback_data.order_id, "accepted")
    response = row["response"] or "(отклик отсутствует)"

    if isinstance(query.message, Message):
        # Присылаем чистый текст отдельным сообщением — удобно копировать/пересылать.
        await query.message.answer(response, parse_mode=None)
        await query.message.edit_reply_markup(reply_markup=None)
    await query.answer("Отклик готов — копируй и отправляй 🚀")


@router.callback_query(OrderAction.filter(F.action == "skip"))
async def on_skip(
    query: CallbackQuery,
    callback_data: OrderAction,
    db: Database,
    owner_id: int,
) -> None:
    if not _is_owner(query.from_user.id, owner_id):
        await query.answer("Недоступно", show_alert=True)
        return

    await db.set_status(callback_data.order_id, "skipped")
    if isinstance(query.message, Message):
        await query.message.edit_reply_markup(reply_markup=None)
    await query.answer("Скипнуто ❌")


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
        reply_markup=order_keyboard(order_id),
        link_preview_options=_NO_PREVIEW,
    )

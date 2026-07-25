"""Роутер заказов: /start и обработчики инлайн-кнопок (copy / refresh)."""

from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.filters import CommandStart
from aiogram.types import CallbackQuery, Message

from database.repositories.lead_repo import LeadRepository
from database.session import Database
from schemas.lead import LeadCreate, LeadRead
from services.response_service import ResponseService
from telegram.callbacks import LeadCB
from telegram.cards import render_card
from telegram.keyboards import lead_keyboard

log = logging.getLogger(__name__)

router = Router(name="leads")


@router.message(CommandStart())
async def on_start(message: Message) -> None:
    await message.answer(
        "👋 <b>kwork_bot</b> на связи.\n"
        "Сюда будут приходить новые заказы Kwork с готовым откликом.\n"
        "Под каждой карточкой: открыть заказ, обновить или скопировать отклик."
    )


@router.callback_query(LeadCB.filter(F.action == "copy"))
async def on_copy(query: CallbackQuery, callback_data: LeadCB, database: Database) -> None:
    async with database.session() as session:
        lead = await LeadRepository(session).get(callback_data.lead_id)
        response = lead.response_text if lead is not None else None

    if not response:
        await query.answer("Отклик пуст — обновите его", show_alert=True)
        return
    if isinstance(query.message, Message):
        # Чистый текст отдельным сообщением — удобно копировать/пересылать.
        await query.message.answer(response, parse_mode=None)
    await query.answer("Отклик отправлен отдельным сообщением 📋")


@router.callback_query(LeadCB.filter(F.action == "refresh"))
async def on_refresh(
    query: CallbackQuery,
    callback_data: LeadCB,
    database: Database,
    response_service: ResponseService,
) -> None:
    async with database.session() as session:
        lead = await LeadRepository(session).get(callback_data.lead_id)
        if lead is None:
            await query.answer("Заказ не найден", show_alert=True)
            return
        data = LeadCreate(
            source=lead.source,
            external_id=lead.external_id,
            title=lead.title,
            url=lead.url,
            description=lead.description,
            budget_raw=lead.budget_raw,
            budget_value=lead.budget_value,
        )
        lead_read = LeadRead.model_validate(lead)

    new_response = await response_service.generate(data)
    if not new_response:
        await query.answer("Не удалось обновить отклик — попробуйте позже", show_alert=True)
        return

    async with database.session() as session:
        await LeadRepository(session).set_response(callback_data.lead_id, new_response)

    if isinstance(query.message, Message):
        await query.message.edit_text(
            render_card(lead_read, new_response),
            reply_markup=lead_keyboard(lead_read.id, lead_read.url),
        )
    await query.answer("Отклик обновлён 🔄")

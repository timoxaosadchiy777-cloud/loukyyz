"""Панель управления пользователя.

Меню: ⚙️ Настройки · 🔍 Проверить сейчас · ⭐ Сохранённые · 🌐 Биржи · ❓ Справка.
Экраны правки фильтров переиспользуются из мастера (:mod:`bot.wizard`).
"""

from __future__ import annotations

import logging

from aiogram import Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, LinkPreviewOptions, Message

from bot import texts
from bot.access import AccessControl
from bot.callbacks import CTX_SETTINGS, EditAction, MenuAction
from bot.screens import (
    LEADS_LIMIT,
    filter_orders,
    render_leads,
    render_menu,
    render_settings,
    render_step,
)
from bot.keyboards import back_to_menu_keyboard
from bot.wizard import apply_sources, show_screen
from database.db import Database

log = logging.getLogger(__name__)

menu_router = Router(name="leadhunter-menu")

_NO_PREVIEW = LinkPreviewOptions(is_disabled=True)

# Сколько свежих лидов просматриваем, подбирая подходящие под фильтры.
_SCAN_LIMIT = 200


@menu_router.message(Command("menu"))
async def on_menu_command(
    message: Message, db: Database, access: AccessControl, state: FSMContext
) -> None:
    user = message.from_user
    if user is None or not await access.has_access(user.id):
        return
    # Открытие меню отменяет незавершённый ввод ключевых слов — иначе следующее
    # сообщение пользователя молча уйдёт в фильтр.
    await state.clear()
    settings = await db.get_user_settings(user.id)
    text, markup = render_menu(settings, await db.user_stats(user.id))
    await message.answer(text, reply_markup=markup)


@menu_router.callback_query(MenuAction.filter())
async def on_menu_action(
    query: CallbackQuery,
    callback_data: MenuAction,
    db: Database,
    access: AccessControl,
    sources=None,
    max_lead_age_hours: int = 0,
) -> None:
    if not await access.has_access(query.from_user.id):
        await query.answer(texts.ERR_NO_ACCESS, show_alert=True)
        return

    settings = await db.get_user_settings(query.from_user.id)
    action = callback_data.action

    if action == "menu":
        text, markup = render_menu(settings, await db.user_stats(query.from_user.id))
    elif action == "settings":
        text, markup = render_settings(settings)
    elif action == "sources":
        await apply_sources(query, db, CTX_SETTINGS, sources)
        await query.answer()
        return
    elif action == "check":
        rows = await db.recent_orders(limit=_SCAN_LIMIT, max_age_hours=max_lead_age_hours)
        matched = filter_orders(rows, settings, limit=LEADS_LIMIT)
        text = render_leads(
            matched,
            title="🔍 Подходящие лиды",
            empty=(
                "Пока ничего под твои фильтры.\n"
                "Бот продолжит следить и пришлёт новые заказы сам."
            ),
        )
        markup = back_to_menu_keyboard()
    elif action == "saved":
        rows = await db.list_saved_leads(query.from_user.id, limit=LEADS_LIMIT)
        text = render_leads(
            rows,
            title="⭐ Сохранённые лиды",
            empty="Тут пусто. Сохраняй заказы кнопкой ❤️ под карточкой.",
        )
        markup = back_to_menu_keyboard()
    else:
        await query.answer()
        return

    await show_screen(query, text, markup)
    await query.answer()


@menu_router.callback_query(EditAction.filter())
async def on_edit_field(
    query: CallbackQuery,
    callback_data: EditAction,
    db: Database,
    access: AccessControl,
    sources=None,
) -> None:
    """Правка одного фильтра: те же экраны, что в мастере, но с возвратом
    на экран настроек."""
    if not await access.has_access(query.from_user.id):
        await query.answer(texts.ERR_NO_ACCESS, show_alert=True)
        return

    if callback_data.field == "sources":
        await apply_sources(query, db, CTX_SETTINGS, sources)
        await query.answer()
        return

    settings = await db.get_user_settings(query.from_user.id)
    text, markup = render_step(callback_data.field, settings, CTX_SETTINGS)
    await show_screen(query, text, markup)
    await query.answer()

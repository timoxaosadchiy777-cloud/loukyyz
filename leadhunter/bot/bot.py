"""Сборка бота, роутер и обработчики инлайн-кнопок."""

from __future__ import annotations

import logging

from aiogram import Bot, Dispatcher, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, LinkPreviewOptions, Message

from bot.access import AccessControl
from bot.admin import admin_router
from bot.callbacks import CrmAction, OrderAction
from bot.cards import render_card
from bot.keyboards import order_keyboard
from bot.menu import menu_router
from bot.screens import render_menu
from bot.wizard import start_wizard, wizard_router
from config import Settings
from core.models import CRM_LABELS, CrmStatus, Order
from database.db import Database

log = logging.getLogger(__name__)

router = Router(name="leadhunter")

_NO_PREVIEW = LinkPreviewOptions(is_disabled=True)


@router.message(CommandStart())
async def on_start(
    message: Message, db: Database, access: AccessControl, state: FSMContext
) -> None:
    user = message.from_user
    if user is None:
        return

    # /start обрывает незавершённый ввод — иначе следующее сообщение уйдёт в него.
    await state.clear()

    # Регистрируем при первом контакте: так администратор видит человека
    # в /users и может выдать ему доступ. Уже выданный доступ не сбрасывается.
    await db.register_user(user.id, user.username or "")

    if not await access.has_access(user.id):
        await message.answer(
            "🔒 <b>LeadHunter</b> — доступ по подписке.\n\n"
            "Твой Telegram ID: <code>{user_id}</code>\n"
            "Отправь его администратору, чтобы получить доступ.".format(user_id=user.id)
        )
        return

    # Первый вход — мастер настройки; дальше сразу панель управления.
    settings = await db.get_user_settings(user.id)
    if not settings.onboarded:
        await start_wizard(message, db, user.id)
        return

    text, markup = render_menu(settings)
    await message.answer(text, reply_markup=markup)


@router.callback_query(OrderAction.filter())
async def on_order_action(
    query: CallbackQuery,
    callback_data: OrderAction,
    db: Database,
    access: AccessControl,
) -> None:
    if not await access.has_access(query.from_user.id):
        await query.answer("Нет доступа", show_alert=True)
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

    if callback_data.action in ("save", "unsave"):
        saved = callback_data.action == "save"
        if saved:
            await db.save_lead(query.from_user.id, callback_data.order_id)
        else:
            await db.unsave_lead(query.from_user.id, callback_data.order_id)
        # Перерисовываем только клавиатуру — текст карточки не меняется.
        if isinstance(query.message, Message):
            try:
                await query.message.edit_reply_markup(
                    reply_markup=order_keyboard(
                        callback_data.order_id, row["crm_status"], saved=saved
                    )
                )
            except Exception:
                log.debug("Клавиатура карточки %s не изменилась", callback_data.order_id)
        await query.answer("Сохранено ⭐" if saved else "Убрано из избранного")
        return

    await query.answer()


@router.callback_query(CrmAction.filter())
async def on_crm_action(
    query: CallbackQuery,
    callback_data: CrmAction,
    db: Database,
    access: AccessControl,
) -> None:
    if not await access.has_access(query.from_user.id):
        await query.answer("Нет доступа", show_alert=True)
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
    saved = await db.is_lead_saved(query.from_user.id, callback_data.order_id)
    if isinstance(query.message, Message):
        try:
            await query.message.edit_text(
                render_card(order, response),
                reply_markup=order_keyboard(callback_data.order_id, status, saved=saved),
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
    dp["access"] = AccessControl(db, settings.owner_id)
    # Админский роутер — первым: его команды видит только владелец.
    dp.include_router(admin_router)
    dp.include_router(menu_router)
    dp.include_router(wizard_router)
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

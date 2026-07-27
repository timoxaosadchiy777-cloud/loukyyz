"""Сборка бота, роутер и обработчики инлайн-кнопок."""

from __future__ import annotations

import logging
from html import escape

from aiogram import Bot, Dispatcher, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, LinkPreviewOptions, Message

from ai.responder import Responder
from bot.access import AccessControl
from bot.admin import admin_router
from bot.callbacks import CrmAction, OrderAction
from bot.cards import render_card
from bot.keyboards import order_keyboard, rewrite_keyboard
from bot.menu import menu_router
from bot.screens import render_menu
from bot.wizard import start_wizard, wizard_router
from config import Settings
from core.models import CRM_LABELS, CrmStatus, LeadState, Order
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


class CardStates(StatesGroup):
    """Ожидание своего варианта отклика (кнопка «✍️ Изменить отклик»)."""

    rewrite = State()


async def personal_card(db: Database, user_id: int, row) -> tuple[str, object]:
    """Карточка глазами конкретного получателя.

    Отклик, статус воронки и признак «сохранено» берём из его доставки: под
    fan-out один лид живёт у каждого пользователя своей жизнью. Пока доставки
    нет (владелец до fan-out, лид из «Проверить сейчас») — падаем на общие
    значения заказа.
    """
    order_id = row["id"]
    delivery = await db.get_delivery(user_id, order_id)

    response = (delivery["response"] if delivery else "") or row["response"]
    crm_status = delivery["crm_status"] if delivery else row["crm_status"]
    saved = bool(delivery and delivery["state"] == LeadState.SAVED)

    order = Order.from_row(row)
    order.crm_status = crm_status or CrmStatus.NEW
    return (
        render_card(order, response or "(отклик отсутствует)"),
        order_keyboard(order_id, order.crm_status, saved=saved),
    )


async def _redraw_card(query: CallbackQuery, db: Database, row) -> None:
    text, markup = await personal_card(db, query.from_user.id, row)
    if isinstance(query.message, Message):
        try:
            await query.message.edit_text(
                text, reply_markup=markup, link_preview_options=_NO_PREVIEW
            )
        except Exception:
            log.debug("Карточка %s не изменилась", row["id"])


@router.callback_query(OrderAction.filter())
async def on_order_action(
    query: CallbackQuery,
    callback_data: OrderAction,
    db: Database,
    access: AccessControl,
    state: FSMContext,
    responder: Responder | None = None,
) -> None:
    if not await access.has_access(query.from_user.id):
        await query.answer("Нет доступа", show_alert=True)
        return

    order_id = callback_data.order_id
    user_id = query.from_user.id
    row = await db.get_order(order_id)
    if row is None:
        await query.answer("Заказ не найден", show_alert=True)
        return

    action = callback_data.action

    if action == "copy":
        delivery = await db.get_delivery(user_id, order_id)
        response = (delivery["response"] if delivery else "") or row["response"]
        if isinstance(query.message, Message):
            # Чистый текст отдельным сообщением — удобно копировать/пересылать.
            await query.message.answer(
                response or "(отклик отсутствует)", parse_mode=None
            )
        await query.answer("Отклик готов — копируй и отправляй 🚀")
        return

    if action in ("save", "unsave"):
        saved = action == "save"
        await db.set_delivery_state(
            user_id, order_id, LeadState.SAVED if saved else LeadState.SENT
        )
        await _redraw_card(query, db, row)
        await query.answer("Сохранено ❤️" if saved else "Убрано из сохранённых")
        return

    if action == "reject":
        await db.set_delivery_state(user_id, order_id, LeadState.REJECTED)
        if isinstance(query.message, Message):
            try:
                # Карточку не удаляем — оставляем след, но убираем действия.
                await query.message.edit_text(
                    f"❌ <s>{escape(row['title'])}</s>\n<i>Отклонён</i>",
                    link_preview_options=_NO_PREVIEW,
                )
            except Exception:
                log.debug("Карточка %s не изменилась", order_id)
        await query.answer("Лид отклонён")
        return

    if action == "rewrite":
        await state.set_state(CardStates.rewrite)
        await state.update_data(order_id=order_id)
        if isinstance(query.message, Message):
            await query.message.answer(
                "✍️ <b>Свой вариант отклика</b>\n\n"
                "Пришли текст одним сообщением — он заменит черновик только у тебя.",
                reply_markup=rewrite_keyboard(order_id),
            )
        await query.answer()
        return

    if action == "regen":
        await _regenerate(query, db, row, responder)
        return

    if action == "cancel_rewrite":
        await state.clear()
        await query.answer("Отменено")
        return

    await query.answer()


async def _regenerate(
    query: CallbackQuery, db: Database, row, responder: Responder | None
) -> None:
    """Просит ИИ написать новый вариант отклика лично для этого пользователя."""
    if responder is None:
        await query.answer("Генерация недоступна", show_alert=True)
        return

    await query.answer("Готовлю новый вариант…")
    order = Order.from_row(row)
    response = await responder.generate(order)
    if not response:
        if isinstance(query.message, Message):
            await query.message.answer("⚠️ Не получилось — ИИ сейчас недоступен.")
        return

    await db.set_delivery_response(query.from_user.id, row["id"], response)
    if isinstance(query.message, Message):
        await query.message.answer(
            "✍️ <b>Новый вариант отклика:</b>\n\n"
            f"<blockquote>{escape(response)}</blockquote>"
        )


@router.message(CardStates.rewrite)
async def on_rewrite_text(
    message: Message,
    db: Database,
    access: AccessControl,
    state: FSMContext,
) -> None:
    """Сохраняет присланный пользователем отклик в его личную доставку."""
    user = message.from_user
    if user is None or not await access.has_access(user.id):
        await state.clear()
        return

    data = await state.get_data()
    order_id = data.get("order_id")
    await state.clear()
    if order_id is None:
        return

    await db.set_delivery_response(user.id, order_id, message.text or "")
    await message.answer("✅ Отклик обновлён — он сохранён только у тебя.")


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

    row = await db.get_order(callback_data.order_id)
    if row is None:
        await query.answer("Заказ не найден", show_alert=True)
        return

    # Статус воронки персональный: под fan-out один заказ ведут независимо
    # несколько человек, и общий crm_status затирал бы чужой прогресс.
    await db.set_delivery_crm(query.from_user.id, callback_data.order_id, status)
    await _redraw_card(query, db, row)
    await query.answer(f"Статус: {CRM_LABELS.get(status, status)}")


def create_bot(settings: Settings) -> Bot:
    return Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )


def create_dispatcher(
    db: Database, settings: Settings, responder: Responder | None = None
) -> Dispatcher:
    dp = Dispatcher()
    # Зависимости прокидываются в хендлеры по имени аргумента.
    dp["db"] = db
    dp["owner_id"] = settings.owner_id
    dp["access"] = AccessControl(db, settings.owner_id)
    # Нужен кнопке «🔄 Сгенерировать заново»; без него она честно скажет,
    # что генерация недоступна.
    dp["responder"] = responder
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

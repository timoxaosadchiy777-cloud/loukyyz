"""Сборка бота, роутер и обработчики инлайн-кнопок."""

from __future__ import annotations

import logging
from html import escape

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    BotCommand,
    BotCommandScopeChat,
    BotCommandScopeDefault,
    CallbackQuery,
    ErrorEvent,
    LinkPreviewOptions,
    Message,
)

from ai.responder import Responder
from bot import texts
from bot.access import AccessControl
from bot.admin import admin_router, announce_request
from bot.callbacks import AccessAction, CrmAction, HelpAction, OrderAction
from bot.cards import render_card, split_plain
from bot.keyboards import (
    help_keyboard,
    order_keyboard,
    request_access_keyboard,
    rewrite_keyboard,
)
from bot.menu import menu_router
from bot.screens import render_menu
from bot.wizard import start_wizard, wizard_router
from config import Settings
from core.models import CRM_LABELS, CrmStatus, LeadState, Order
from core.ratelimit import RateLimiter
from database.db import Database

log = logging.getLogger(__name__)

router = Router(name="leadhunter")

_NO_PREVIEW = LinkPreviewOptions(is_disabled=True)

# Перегенерация отклика — это запрос к модели, то есть деньги (или занятая
# очередь локального Ollama). Без ограничения один пользователь, кликающий
# «Сгенерировать заново», выжигает квоту провайдера на всех остальных.
_regen_limiter = RateLimiter(limit=5, window=300)

# Заявки на доступ. После отказа админа заявка снимается, и без ограничения
# пользователь мог слать её заново хоть каждую секунду, заваливая владельца.
_request_limiter = RateLimiter(limit=2, window=3600)


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
        # Продающий экран + заявка в один тап: копировать ID и искать
        # администратора вручную не нужно.
        await message.answer(
            texts.welcome_locked(user.id),
            reply_markup=request_access_keyboard(user.id),
        )
        return

    # Первый вход — мастер настройки; дальше сразу панель управления.
    settings = await db.get_user_settings(user.id)
    if not settings.onboarded:
        await start_wizard(message, db, user.id)
        return

    text, markup = render_menu(settings, await db.user_stats(user.id))
    await message.answer(text, reply_markup=markup)


@router.message(Command("help"))
async def on_help(message: Message, access: AccessControl) -> None:
    user = message.from_user
    if user is None:
        return
    if not await access.has_access(user.id):
        await message.answer(texts.ERR_NO_ACCESS)
        return
    await message.answer(texts.HELP, reply_markup=help_keyboard())


@router.callback_query(HelpAction.filter())
async def on_help_button(query: CallbackQuery, access: AccessControl) -> None:
    if not await access.has_access(query.from_user.id):
        await query.answer(texts.ERR_NO_ACCESS, show_alert=True)
        return
    if isinstance(query.message, Message):
        try:
            await query.message.edit_text(texts.HELP, reply_markup=help_keyboard())
        except Exception:
            log.debug("Справка не изменилась")
    await query.answer()


@router.callback_query(AccessAction.filter(F.action == "request"))
async def on_access_request(
    query: CallbackQuery, callback_data: AccessAction, db: Database, owner_id: int
) -> None:
    """Пользователь нажал «Запросить доступ» на стартовом экране."""
    user = query.from_user
    is_new = await db.request_access(user.id, user.username or "")

    if not is_new:
        await query.answer(texts.REQUEST_ALREADY_SENT, show_alert=True)
        return

    if _request_limiter.check(user.id) > 0:
        # Заявка сохранена, но администратора больше не дёргаем.
        await query.answer(texts.REQUEST_SENT, show_alert=True)
        return

    await announce_request(query.bot, owner_id, user.id, user.username or "")
    if isinstance(query.message, Message):
        try:
            await query.message.edit_text(texts.REQUEST_SENT)
        except Exception:
            log.debug("Экран заявки не изменился")
    await query.answer("Заявка отправлена ✅")


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


async def _may_touch(
    db: Database, access: AccessControl, user_id: int, order_id: int
) -> bool:
    """Имеет ли пользователь право на действия с этим лидом.

    Право даёт факт доставки. Владельцу разрешаем всё: у лидов, пришедших до
    fan-out, записи о доставке нет, и иначе он потерял бы к ним доступ.
    """
    if access.is_admin(user_id) or access.dev_mode:
        return True
    return await db.was_delivered(user_id, order_id)


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
        await query.answer(texts.ERR_NO_ACCESS, show_alert=True)
        return

    order_id = callback_data.order_id
    user_id = query.from_user.id
    row = await db.get_order(order_id)
    if row is None:
        await query.answer(texts.ERR_ORDER_GONE, show_alert=True)
        return

    # order_id приходит из callback_data, то есть от клиента. Без этой проверки
    # любой пользователь с доступом мог перебором id вытащить текст и отклик
    # чужого лида — включая тот, что его фильтры не пропустили.
    if not await _may_touch(db, access, user_id, order_id):
        await query.answer(texts.ERR_ORDER_GONE, show_alert=True)
        return

    action = callback_data.action

    if action == "copy":
        delivery = await db.get_delivery(user_id, order_id)
        response = (delivery["response"] if delivery else "") or row["response"]
        if isinstance(query.message, Message):
            # Чистый текст отдельным сообщением — удобно копировать/пересылать.
            # Длинный отклик режем на части: обрезать его нельзя, пользователю
            # нужен весь текст, а Telegram не примет больше 4096 символов.
            for part in split_plain(response) or ["(отклик отсутствует)"]:
                await query.message.answer(part, parse_mode=None)
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
        wait = _regen_limiter.check(user_id)
        if wait > 0:
            await query.answer(texts.regen_too_often(wait), show_alert=True)
            return
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
        await query.answer(texts.ERR_GENERATION_OFF, show_alert=True)
        return

    await query.answer("Готовлю новый вариант…")
    order = Order.from_row(row)
    response = await responder.generate(order)
    if not response:
        if isinstance(query.message, Message):
            await query.message.answer(texts.ERR_AI_DOWN)
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
        await query.answer(texts.ERR_NO_ACCESS, show_alert=True)
        return

    status = callback_data.status
    if status not in CrmStatus.ALL:
        await query.answer(texts.ERR_UNKNOWN_STATUS, show_alert=True)
        return

    row = await db.get_order(callback_data.order_id)
    if row is None:
        await query.answer(texts.ERR_ORDER_GONE, show_alert=True)
        return

    if not await _may_touch(db, access, query.from_user.id, callback_data.order_id):
        await query.answer(texts.ERR_ORDER_GONE, show_alert=True)
        return

    # Статус воронки персональный: под fan-out один заказ ведут независимо
    # несколько человек, и общий crm_status затирал бы чужой прогресс.
    await db.set_delivery_crm(query.from_user.id, callback_data.order_id, status)
    await _redraw_card(query, db, row)
    await query.answer(f"Статус: {CRM_LABELS.get(status, status)}")


@router.errors()
async def on_error(event: ErrorEvent) -> bool:
    """Ловит всё, что упало в хендлере.

    Пользователь получает человеческое сообщение вместо тишины (или, хуже,
    вечных «часиков» на кнопке), а подробности уходят в лог.
    """
    log.exception("Необработанная ошибка: %s", event.exception)

    update = event.update
    try:
        if update.callback_query is not None:
            await update.callback_query.answer(texts.ERR_GENERIC, show_alert=True)
        elif update.message is not None:
            await update.message.answer(texts.ERR_GENERIC)
    except Exception:
        log.debug("Не удалось сообщить об ошибке пользователю")
    return True


# Меню команд в синей кнопке Telegram. Владелец видит ещё и админские.
_USER_COMMANDS = [
    BotCommand(command="menu", description="🎯 Панель управления"),
    BotCommand(command="help", description="❓ Как это работает"),
    BotCommand(command="start", description="🚀 Начать заново"),
]

_ADMIN_COMMANDS = _USER_COMMANDS + [
    BotCommand(command="admin", description="🛠 Админ-панель"),
    BotCommand(command="users", description="👥 Список пользователей"),
]


async def setup_commands(bot: Bot, owner_id: int) -> None:
    """Регистрирует подсказки команд. Сбой не должен мешать запуску бота."""
    try:
        await bot.set_my_commands(_USER_COMMANDS, scope=BotCommandScopeDefault())
        if owner_id:
            await bot.set_my_commands(
                _ADMIN_COMMANDS, scope=BotCommandScopeChat(chat_id=owner_id)
            )
    except Exception as exc:  # noqa: BLE001 — косметика, не критично
        log.warning("Не удалось задать меню команд: %s", exc)


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
    dp["access"] = AccessControl(db, settings.owner_id, settings.dev_mode)
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

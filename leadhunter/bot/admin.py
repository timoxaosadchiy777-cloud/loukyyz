"""Админский режим: панель, выдача доступа и заявки.

Доступно только администратору (``OWNER_ID``). Для всех остальных команды
молчат — бот не подсказывает существование админки.

Два пути выдать доступ:
  * **из заявки** — пользователь нажал «📨 Запросить доступ», админу пришло
    уведомление с кнопками; решение в один тап;
  * **из панели** — ``/admin`` → 👥 Пользователи, тап по строке переключает.

Текстовые команды ``/grant``, ``/revoke``, ``/users`` сохранены: ими удобно
пользоваться с клавиатуры и из скриптов.
"""

from __future__ import annotations

import html
import logging

from aiogram import Bot, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import CallbackQuery, Message

from bot import texts
from bot.access import AccessControl
from bot.callbacks import AccessAction, AdminAction, UserAction
from bot.keyboards import (
    ADMIN_PAGE_SIZE,
    access_request_keyboard,
    admin_keyboard,
    admin_requests_keyboard,
    admin_users_keyboard,
    back_to_admin_keyboard,
)
from database.db import Database

log = logging.getLogger(__name__)

admin_router = Router(name="leadhunter-admin")

# Сколько пользователей показываем в текстовом /users за раз.
_USERS_LIMIT = 50


def _parse_user_id(command: CommandObject) -> int | None:
    """Достаёт telegram_id из аргументов команды. ``None`` — если не разобрать."""
    raw = (command.args or "").strip().split()
    if not raw:
        return None
    try:
        user_id = int(raw[0])
    except ValueError:
        return None
    return user_id if user_id > 0 else None


def _handle(row) -> str:
    username = html.escape(row["username"] or "")
    return f" @{username}" if username else ""


async def notify(bot: Bot, user_id: int, text: str, **kwargs) -> bool:
    """Пишет пользователю, не роняя вызывающий код.

    Пользователь мог не начинать диалог с ботом или заблокировать его — тогда
    Telegram вернёт ошибку, и это нормально: действие администратора уже
    выполнено.
    """
    try:
        await bot.send_message(user_id, text, **kwargs)
        return True
    except Exception as exc:  # noqa: BLE001 — доставка не критична
        log.info("Не удалось уведомить %s: %s", user_id, exc)
        return False


async def _grant(bot: Bot, db: Database, user_id: int) -> None:
    await db.set_paid_status(user_id, True)
    await db.clear_access_request(user_id)
    await notify(bot, user_id, texts.ACCESS_GRANTED)


async def _revoke(bot: Bot, db: Database, user_id: int, text: str) -> None:
    await db.set_paid_status(user_id, False)
    await db.clear_access_request(user_id)
    await notify(bot, user_id, text)


# --- Заявки на доступ -----------------------------------------------------


@admin_router.callback_query(AccessAction.filter())
async def on_access_decision(
    query: CallbackQuery,
    callback_data: AccessAction,
    db: Database,
    access: AccessControl,
) -> None:
    """Решение администратора по заявке — из уведомления или из панели."""
    if not access.is_admin(query.from_user.id):
        await query.answer(texts.ERR_NO_ACCESS, show_alert=True)
        return

    user_id = callback_data.user_id
    if callback_data.action == "grant":
        await _grant(query.bot, db, user_id)
        await query.answer("Доступ выдан ✅")
    elif callback_data.action == "decline":
        await _revoke(query.bot, db, user_id, texts.ACCESS_DECLINED)
        await query.answer("Заявка отклонена")
    else:
        await query.answer()
        return

    await _show_requests(query, db)


async def announce_request(bot: Bot, owner_id: int, user_id: int, username: str) -> None:
    """Отправляет администратору заявку с кнопками решения."""
    if not owner_id:
        log.warning("Заявка от %s: OWNER_ID не задан, некому показать", user_id)
        return
    await notify(
        bot,
        owner_id,
        texts.access_request(user_id, username),
        reply_markup=access_request_keyboard(user_id),
    )


# --- Панель ---------------------------------------------------------------


async def _panel_text(db: Database) -> str:
    stats = await db.stats()
    return (
        f"{texts.ADMIN_PANEL}\n\n"
        f"👥 Пользователей: <b>{stats['users_total']}</b> "
        f"(с доступом {stats['users_paid']})\n"
        f"📨 Заявок: <b>{stats['requests']}</b>"
    )


@admin_router.message(Command("admin"))
async def on_admin_command(
    message: Message, db: Database, access: AccessControl
) -> None:
    if not access.is_admin(message.from_user.id if message.from_user else None):
        return
    stats = await db.stats()
    await message.answer(
        await _panel_text(db), reply_markup=admin_keyboard(stats["requests"])
    )


async def _edit(query: CallbackQuery, text: str, markup) -> None:
    if isinstance(query.message, Message):
        try:
            await query.message.edit_text(text, reply_markup=markup)
        except Exception:
            log.debug("Экран админки не изменился")


async def _show_panel(query: CallbackQuery, db: Database) -> None:
    stats = await db.stats()
    await _edit(query, await _panel_text(db), admin_keyboard(stats["requests"]))


async def _show_users(query: CallbackQuery, db: Database, page: int) -> None:
    total, paid = await db.count_users()
    if not total:
        await _edit(query, texts.ADMIN_NO_USERS, back_to_admin_keyboard())
        return

    # Страницу берём из базы, а не режем выборку в Python: иначе всё, что не
    # попало в первую сотню, становится недоступным для управления.
    last_page = max(0, (total - 1) // ADMIN_PAGE_SIZE)
    page = min(max(0, page), last_page)
    rows = await db.list_users(limit=ADMIN_PAGE_SIZE, offset=page * ADMIN_PAGE_SIZE)

    text = (
        f"👥 <b>Пользователи</b> — всего {total}, с доступом {paid}\n\n"
        "Тап по строке переключает доступ."
    )
    await _edit(query, text, admin_users_keyboard(rows, page, total))


async def _show_requests(query: CallbackQuery, db: Database) -> None:
    rows = await db.list_access_requests()
    if not rows:
        await _edit(query, texts.ADMIN_NO_REQUESTS, back_to_admin_keyboard())
        return

    lines = [f"📨 <b>Заявки на доступ</b> — {len(rows)}", ""]
    lines += [f"• <code>{row['telegram_id']}</code>{_handle(row)}" for row in rows]
    await _edit(query, "\n".join(lines), admin_requests_keyboard(rows))


async def _show_stats(query: CallbackQuery, db: Database) -> None:
    s = await db.stats()
    text = (
        "📊 <b>Статистика</b>\n\n"
        f"👥 Пользователей: <b>{s['users_total']}</b>\n"
        f"✅ С доступом: <b>{s['users_paid']}</b>\n"
        f"📨 Заявок в очереди: <b>{s['requests']}</b>\n\n"
        f"🎯 Лидов в базе: <b>{s['orders_total']}</b>\n"
        f"📬 Доставлено пользователям: <b>{s['orders_delivered']}</b>\n"
        f"📮 Всего доставок: <b>{s['deliveries']}</b>\n"
        f"❤️ Сохранено: <b>{s['saved']}</b>"
    )
    await _edit(query, text, back_to_admin_keyboard())


@admin_router.callback_query(AdminAction.filter())
async def on_admin_action(
    query: CallbackQuery,
    callback_data: AdminAction,
    db: Database,
    access: AccessControl,
) -> None:
    if not access.is_admin(query.from_user.id):
        await query.answer(texts.ERR_NO_ACCESS, show_alert=True)
        return

    action = callback_data.action
    if action == "users":
        await _show_users(query, db, max(0, callback_data.page))
    elif action == "requests":
        await _show_requests(query, db)
    elif action == "stats":
        await _show_stats(query, db)
    else:
        await _show_panel(query, db)
    await query.answer()


@admin_router.callback_query(UserAction.filter())
async def on_user_toggle(
    query: CallbackQuery,
    callback_data: UserAction,
    db: Database,
    access: AccessControl,
) -> None:
    """Переключение доступа тапом по строке списка."""
    if not access.is_admin(query.from_user.id):
        await query.answer(texts.ERR_NO_ACCESS, show_alert=True)
        return

    if not callback_data.grant and callback_data.user_id == access.owner_id:
        await query.answer(texts.ADMIN_CANNOT_REVOKE_SELF, show_alert=True)
        return

    if callback_data.grant:
        await _grant(query.bot, db, callback_data.user_id)
        await query.answer("Доступ выдан ✅")
    else:
        await _revoke(query.bot, db, callback_data.user_id, texts.ACCESS_REVOKED)
        await query.answer("Доступ отозван")

    await _show_users(query, db, max(0, callback_data.page))


# --- Текстовые команды ----------------------------------------------------


@admin_router.message(Command("grant"))
async def on_grant(
    message: Message,
    command: CommandObject,
    db: Database,
    access: AccessControl,
) -> None:
    if not access.is_admin(message.from_user.id if message.from_user else None):
        return

    user_id = _parse_user_id(command)
    if user_id is None:
        await message.answer(texts.ADMIN_GRANT_USAGE)
        return

    await _grant(message.bot, db, user_id)
    await message.answer(f"✅ Доступ выдан: <code>{user_id}</code>")


@admin_router.message(Command("revoke"))
async def on_revoke(
    message: Message,
    command: CommandObject,
    db: Database,
    access: AccessControl,
) -> None:
    if not access.is_admin(message.from_user.id if message.from_user else None):
        return

    user_id = _parse_user_id(command)
    if user_id is None:
        await message.answer(texts.ADMIN_REVOKE_USAGE)
        return

    # Администратора отозвать нельзя: его доступ не хранится в users и
    # проверяется раньше базы — иначе можно случайно закрыть себе бота.
    if user_id == access.owner_id:
        await message.answer(texts.ADMIN_CANNOT_REVOKE_SELF)
        return

    await _revoke(message.bot, db, user_id, texts.ACCESS_REVOKED)
    await message.answer(f"🚫 Доступ отозван: <code>{user_id}</code>")


@admin_router.message(Command("users"))
async def on_users(message: Message, db: Database, access: AccessControl) -> None:
    if not access.is_admin(message.from_user.id if message.from_user else None):
        return

    rows = await db.list_users(limit=_USERS_LIMIT)
    total, paid = await db.count_users()

    if not rows:
        await message.answer(texts.ADMIN_NO_USERS)
        return

    lines = [f"👥 <b>Пользователи</b> — всего {total}, с доступом {paid}\n"]
    for row in rows:
        mark = "✅" if row["paid_status"] else "🔒"
        lines.append(f"{mark} <code>{row['telegram_id']}</code>{_handle(row)}")

    if total > len(rows):
        lines.append(f"\n… и ещё {total - len(rows)}")

    await message.answer("\n".join(lines))

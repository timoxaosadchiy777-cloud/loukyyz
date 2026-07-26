"""Админские команды: выдача, отзыв и просмотр доступа.

Доступны только администратору (``OWNER_ID``). Для всех остальных команды
молчат — бот не подсказывает существование админки.

    /grant <telegram_id>   — выдать доступ
    /revoke <telegram_id>  — отобрать доступ
    /users                 — список пользователей
"""

from __future__ import annotations

import html
import logging

from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message

from bot.access import AccessControl
from database.db import Database

log = logging.getLogger(__name__)

admin_router = Router(name="leadhunter-admin")

# Сколько пользователей показываем в /users за раз.
_USERS_LIMIT = 50


def _parse_user_id(command: CommandObject) -> int | None:
    """Достаёт telegram_id из аргументов команды. ``None`` — если его не разобрать."""
    raw = (command.args or "").strip().split()
    if not raw:
        return None
    try:
        user_id = int(raw[0])
    except ValueError:
        return None
    return user_id if user_id > 0 else None


async def _notify(message: Message, user_id: int, text: str) -> None:
    """Уведомляет пользователя об изменении доступа (best-effort).

    Пользователь мог ни разу не написать боту — тогда Telegram вернёт ошибку,
    и это нормально: команда администратора всё равно уже выполнена.
    """
    try:
        await message.bot.send_message(user_id, text)
    except Exception as exc:  # noqa: BLE001 — доставка не критична
        log.info("Не удалось уведомить %s об изменении доступа: %s", user_id, exc)


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
        await message.answer(
            "Формат: <code>/grant telegram_id</code>\nНапример: <code>/grant 123456789</code>"
        )
        return

    await db.set_paid_status(user_id, True)
    await message.answer(f"✅ Доступ выдан: <code>{user_id}</code>")
    await _notify(message, user_id, "✅ Доступ к LeadHunter открыт. Нажми /start.")


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
        await message.answer(
            "Формат: <code>/revoke telegram_id</code>\nНапример: <code>/revoke 123456789</code>"
        )
        return

    # Администратора отозвать нельзя: его доступ не хранится в users и
    # проверяется раньше базы — иначе можно случайно закрыть себе бота.
    if user_id == access.owner_id:
        await message.answer("❌ Нельзя отозвать доступ у администратора.")
        return

    await db.set_paid_status(user_id, False)
    await message.answer(f"🚫 Доступ отозван: <code>{user_id}</code>")
    await _notify(message, user_id, "🚫 Доступ к LeadHunter закрыт.")


@admin_router.message(Command("users"))
async def on_users(message: Message, db: Database, access: AccessControl) -> None:
    if not access.is_admin(message.from_user.id if message.from_user else None):
        return

    rows = await db.list_users(limit=_USERS_LIMIT)
    total, paid = await db.count_users()

    if not rows:
        await message.answer("Пользователей пока нет.")
        return

    lines = [f"👥 <b>Пользователи</b> — всего {total}, с доступом {paid}\n"]
    for row in rows:
        mark = "✅" if row["paid_status"] else "🔒"
        username = html.escape(row["username"] or "")
        handle = f" @{username}" if username else ""
        lines.append(f"{mark} <code>{row['telegram_id']}</code>{handle}")

    if total > len(rows):
        lines.append(f"\n… и ещё {total - len(rows)}")

    await message.answer("\n".join(lines))

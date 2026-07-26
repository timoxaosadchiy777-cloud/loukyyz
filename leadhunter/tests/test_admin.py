"""Тесты админских команд /grant, /revoke, /users."""

from __future__ import annotations

from dataclasses import dataclass

import pytest
import pytest_asyncio

from bot.access import AccessControl
from bot.admin import on_grant, on_revoke, on_users
from database.db import Database

OWNER = 100
STRANGER = 200
TARGET = 300


@dataclass
class _Command:
    """Заглушка aiogram CommandObject — хендлеры читают только args."""

    args: str | None = None


class _FakeBot:
    def __init__(self, fail: bool = False) -> None:
        self.sent: list[tuple[int, str]] = []
        self._fail = fail

    async def send_message(self, chat_id: int, text: str, **kwargs) -> None:
        if self._fail:
            raise RuntimeError("bot was blocked by the user")
        self.sent.append((chat_id, text))


@dataclass
class _User:
    id: int


class _FakeMessage:
    """Минимальный Message: from_user, answer() и bot."""

    def __init__(self, user_id: int, bot: _FakeBot | None = None) -> None:
        self.from_user = _User(user_id)
        self.bot = bot or _FakeBot()
        self.answers: list[str] = []

    async def answer(self, text: str, **kwargs) -> None:
        self.answers.append(text)


@pytest_asyncio.fixture
async def db(tmp_path):
    database = Database(str(tmp_path / "admin.db"))
    await database.connect()
    try:
        yield database
    finally:
        await database.close()


@pytest.fixture
def access(db):
    return AccessControl(db, owner_id=OWNER)


# --- /grant ---------------------------------------------------------------


async def test_grant_gives_access(db, access) -> None:
    message = _FakeMessage(OWNER)
    await on_grant(message, _Command(str(TARGET)), db, access)

    assert await access.has_access(TARGET) is True
    assert "Доступ выдан" in message.answers[0]
    # Пользователь уведомлён об открытии доступа.
    assert message.bot.sent[0][0] == TARGET


async def test_grant_rejects_non_admin(db, access) -> None:
    message = _FakeMessage(STRANGER)
    await on_grant(message, _Command(str(TARGET)), db, access)

    assert await access.has_access(TARGET) is False
    assert message.answers == []  # чужому команда не отвечает вовсе


async def test_grant_without_argument_shows_usage(db, access) -> None:
    message = _FakeMessage(OWNER)
    await on_grant(message, _Command(None), db, access)
    assert "/grant telegram_id" in message.answers[0]


async def test_grant_with_garbage_argument(db, access) -> None:
    message = _FakeMessage(OWNER)
    await on_grant(message, _Command("не_число"), db, access)
    assert "/grant telegram_id" in message.answers[0]


async def test_grant_survives_undeliverable_notification(db, access) -> None:
    """Пользователь не писал боту — доступ всё равно выдан."""
    message = _FakeMessage(OWNER, bot=_FakeBot(fail=True))
    await on_grant(message, _Command(str(TARGET)), db, access)

    assert await access.has_access(TARGET) is True
    assert "Доступ выдан" in message.answers[0]


# --- /revoke --------------------------------------------------------------


async def test_revoke_takes_access_away(db, access) -> None:
    await db.set_paid_status(TARGET, True)

    message = _FakeMessage(OWNER)
    await on_revoke(message, _Command(str(TARGET)), db, access)

    assert await access.has_access(TARGET) is False
    assert "Доступ отозван" in message.answers[0]


async def test_revoke_rejects_non_admin(db, access) -> None:
    await db.set_paid_status(TARGET, True)

    message = _FakeMessage(STRANGER)
    await on_revoke(message, _Command(str(TARGET)), db, access)

    assert await access.has_access(TARGET) is True
    assert message.answers == []


async def test_admin_cannot_revoke_himself(db, access) -> None:
    message = _FakeMessage(OWNER)
    await on_revoke(message, _Command(str(OWNER)), db, access)

    assert await access.has_access(OWNER) is True
    assert "администратора" in message.answers[0]


# --- /users ---------------------------------------------------------------


async def test_users_lists_paid_and_free(db, access) -> None:
    await db.register_user(STRANGER, "vasya")
    await db.set_paid_status(TARGET, True, username="petya")

    message = _FakeMessage(OWNER)
    await on_users(message, db, access)

    text = message.answers[0]
    assert "всего 2, с доступом 1" in text
    assert f"✅ <code>{TARGET}</code>" in text
    assert f"🔒 <code>{STRANGER}</code>" in text
    assert "@vasya" in text


async def test_users_on_empty_base(db, access) -> None:
    message = _FakeMessage(OWNER)
    await on_users(message, db, access)
    assert "Пользователей пока нет" in message.answers[0]


async def test_users_rejects_non_admin(db, access) -> None:
    await db.register_user(STRANGER, "vasya")

    message = _FakeMessage(STRANGER)
    await on_users(message, db, access)
    assert message.answers == []

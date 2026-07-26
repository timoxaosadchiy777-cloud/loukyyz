"""Общие фикстуры для тестов бота.

Хендлеры — обычные async-функции, поэтому вызываем их напрямую, подставляя
настоящие объекты aiogram (код проверяет ``isinstance(msg, Message)``).
Подклассы перехватывают отправку и складывают её в общий журнал.

Фабрики сообщений отдаются ФИКСТУРАМИ, а не импортом: pytest загружает этот
файл под своим именем модуля, и `from tests.conftest import ...` в тесте создал
бы вторую копию модуля — со своим, всегда пустым журналом.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
import pytest_asyncio
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import CallbackQuery, Chat, InlineKeyboardMarkup, Message, User

from bot.access import AccessControl
from database.db import Database
from tests.helpers import OWNER, USER

# Журнал отправленного: (вид, текст, клавиатура). Чистится фикстурой `rec`.
_RECORD: list[tuple[str, str, InlineKeyboardMarkup | None]] = []


class _RecordingMessage(Message):
    async def answer(self, text: str, **kwargs):
        _RECORD.append(("answer", text, kwargs.get("reply_markup")))
        return self

    async def edit_text(self, text: str, **kwargs):
        _RECORD.append(("edit", text, kwargs.get("reply_markup")))
        return self

    async def edit_reply_markup(self, **kwargs):
        _RECORD.append(("markup", "", kwargs.get("reply_markup")))
        return self


class _RecordingQuery(CallbackQuery):
    async def answer(self, text: str | None = None, **kwargs):
        _RECORD.append(("alert", text or "", None))


class Journal:
    """Читалка журнала отправленного — чтобы тесты были декларативными."""

    def __init__(self, record: list) -> None:
        self._record = record

    @property
    def texts(self) -> list[str]:
        return [text for kind, text, _ in self._record if kind != "alert"]

    @property
    def alerts(self) -> list[str]:
        return [text for kind, text, _ in self._record if kind == "alert"]

    @property
    def last_text(self) -> str:
        return self.texts[-1] if self.texts else ""

    @property
    def last_markup(self) -> InlineKeyboardMarkup | None:
        for _, _, markup in reversed(self._record):
            if markup is not None:
                return markup
        return None

    def has(self, needle: str) -> bool:
        return any(needle in text for text in self.texts)


def _message(user_id: int, text: str = "") -> Message:
    return _RecordingMessage(
        message_id=1,
        date=datetime.now(timezone.utc),
        chat=Chat(id=user_id, type="private"),
        from_user=User(id=user_id, is_bot=False, first_name="Тест"),
        text=text,
    )


@pytest.fixture
def rec() -> Journal:
    _RECORD.clear()
    return Journal(_RECORD)


@pytest.fixture
def msg():
    """Фабрика входящих сообщений: ``msg()`` / ``msg(STRANGER, text='...')``."""
    return lambda user_id=USER, text="": _message(user_id, text)


@pytest.fixture
def cq():
    """Фабрика нажатий на инлайн-кнопку."""

    def _make(user_id: int = USER, data: str = "") -> CallbackQuery:
        return _RecordingQuery(
            id="1",
            from_user=User(id=user_id, is_bot=False, first_name="Тест"),
            chat_instance="chat-instance",
            message=_message(user_id),
            data=data,
        )

    return _make


@pytest_asyncio.fixture
async def bot_db(tmp_path):
    """База с одним оплаченным пользователем (USER) и владельцем OWNER."""
    database = Database(str(tmp_path / "bot.db"))
    await database.connect()
    await database.set_paid_status(USER, True, username="tester")
    try:
        yield database
    finally:
        await database.close()


@pytest.fixture
def access(bot_db) -> AccessControl:
    return AccessControl(bot_db, owner_id=OWNER)


@pytest.fixture
def fsm() -> FSMContext:
    return FSMContext(
        storage=MemoryStorage(),
        key=StorageKey(bot_id=1, chat_id=USER, user_id=USER),
    )

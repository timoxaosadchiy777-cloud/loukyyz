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


class RecordingBot:
    """Подставной Bot: ловит исходящие сообщения (уведомления, заявки)."""

    def __init__(self) -> None:
        self.sent: list[tuple[int, str, InlineKeyboardMarkup | None]] = []

    async def send_message(self, chat_id: int, text: str, **kwargs):
        self.sent.append((chat_id, text, kwargs.get("reply_markup")))

    def to(self, chat_id: int) -> list[str]:
        return [text for target, text, _ in self.sent if target == chat_id]

    @property
    def chats(self) -> list[int]:
        return [target for target, _, _ in self.sent]

    def markup_for(self, chat_id: int) -> InlineKeyboardMarkup | None:
        for target, _, markup in reversed(self.sent):
            if target == chat_id and markup is not None:
                return markup
        return None


def _message(user_id: int, text: str = "", bot=None) -> Message:
    # Объект бота у aiogram приходит из контекста валидации — только так его
    # можно подставить, не поднимая настоящий Bot с токеном.
    return _RecordingMessage.model_validate(
        {
            "message_id": 1,
            "date": datetime.now(timezone.utc),
            "chat": Chat(id=user_id, type="private"),
            "from_user": User(id=user_id, is_bot=False, first_name="Тест"),
            "text": text,
        },
        context={"bot": bot},
    )


@pytest.fixture
def rec() -> Journal:
    _RECORD.clear()
    return Journal(_RECORD)


@pytest.fixture
def tg_bot() -> RecordingBot:
    """Подставной Bot, доступный хендлерам как ``message.bot`` / ``query.bot``."""
    return RecordingBot()


@pytest.fixture
def msg(tg_bot):
    """Фабрика входящих сообщений: ``msg()`` / ``msg(STRANGER, text='...')``."""
    return lambda user_id=USER, text="": _message(user_id, text, tg_bot)


@pytest.fixture
def cq(tg_bot):
    """Фабрика нажатий на инлайн-кнопку."""

    def _make(user_id: int = USER, data: str = "") -> CallbackQuery:
        return _RecordingQuery.model_validate(
            {
                "id": "1",
                "from_user": User(id=user_id, is_bot=False, first_name="Тест"),
                "chat_instance": "chat-instance",
                "message": _message(user_id, bot=tg_bot),
                "data": data,
            },
            context={"bot": tg_bot},
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

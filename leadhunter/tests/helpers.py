"""Инспекция инлайн-клавиатур в тестах (без состояния).

Всё, что хранит состояние между вызовами, живёт в ``conftest.py`` фикстурами:
модуль conftest пытest загружает под собственным именем, и импорт его же из
теста создал бы вторую копию с отдельным журналом.
"""

from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup

OWNER = 100
USER = 500
STRANGER = 999


def buttons(markup: InlineKeyboardMarkup | None) -> list[tuple[str, str]]:
    """Плоский список кнопок клавиатуры: (подпись, callback_data)."""
    if markup is None:
        return []
    return [(b.text, b.callback_data) for row in markup.inline_keyboard for b in row]


def labels(markup: InlineKeyboardMarkup | None) -> list[str]:
    return [text for text, _ in buttons(markup)]


def callback_for(markup: InlineKeyboardMarkup | None, needle: str) -> str:
    """callback_data первой кнопки, в подписи которой встречается ``needle``."""
    for text, data in buttons(markup):
        if needle in text:
            return data
    raise AssertionError(f"Кнопка {needle!r} не найдена среди {labels(markup)}")

"""Мастер настройки и правка фильтров.

Один набор экранов обслуживает два сценария (см. ``ctx`` в callback-данных):

  * :data:`~bot.callbacks.CTX_WIZARD` — мастер после ``/start``: шаги идут
    подряд, в конце выставляется ``onboarded``;
  * :data:`~bot.callbacks.CTX_SETTINGS` — правка одного фильтра из настроек,
    возврат сразу на экран настроек.

Единственный текстовый ввод — свои ключевые слова; для него нужен FSM.
Всё остальное делается инлайн-кнопками.
"""

from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from bot.access import AccessControl
from bot.callbacks import (
    CTX_SETTINGS,
    CTX_WIZARD,
    BudgetAction,
    ToggleAction,
    WizardAction,
)
from bot.screens import (
    render_keywords_prompt,
    render_menu,
    render_settings,
    render_step,
    render_wizard_intro,
)
from core.user_settings import CATEGORIES, KEYWORD_PRESETS, UserSettings
from database.db import Database

log = logging.getLogger(__name__)

wizard_router = Router(name="leadhunter-wizard")

_FIRST_STEP = "sources"


class WizardStates(StatesGroup):
    """Ожидание своих ключевых слов текстом."""

    keywords = State()


async def show_screen(query: CallbackQuery, text: str, markup) -> None:
    """Перерисовывает экран на месте, гася «message is not modified»."""
    if isinstance(query.message, Message):
        try:
            await query.message.edit_text(text, reply_markup=markup)
        except Exception:
            log.debug("Экран не изменился")


async def start_wizard(message: Message, db: Database, user_id: int) -> None:
    """Запускает мастер: приветствие + первый шаг."""
    settings = await db.get_user_settings(user_id)
    await message.answer(render_wizard_intro())
    text, markup = render_step(_FIRST_STEP, settings, CTX_WIZARD)
    await message.answer(text, reply_markup=markup)


def _index(value: str, presets: tuple[str, ...]) -> str | None:
    """Разбирает индекс пресета из callback_data (данные приходят извне)."""
    try:
        return presets[int(value)]
    except (ValueError, IndexError):
        return None


async def _rerender(
    query: CallbackQuery, step: str, settings: UserSettings, ctx: str
) -> None:
    text, markup = render_step(step, settings, ctx)
    await show_screen(query, text, markup)


# --- Навигация по шагам ---------------------------------------------------


@wizard_router.callback_query(WizardAction.filter())
async def on_wizard_step(
    query: CallbackQuery,
    callback_data: WizardAction,
    db: Database,
    access: AccessControl,
    state: FSMContext,
) -> None:
    if not await access.has_access(query.from_user.id):
        await query.answer("Нет доступа", show_alert=True)
        return

    settings = await db.get_user_settings(query.from_user.id)
    step = callback_data.step

    if step == "kw_input":
        # Запоминаем, куда вернуться после ввода: мастер или настройки.
        await state.set_state(WizardStates.keywords)
        await state.update_data(ctx=callback_data.ctx)
        await show_screen(query, render_keywords_prompt(settings), None)
        await query.answer()
        return

    if step == "done":
        await db.save_user_settings(
            query.from_user.id, settings.replace(onboarded=True)
        )
        text, markup = render_menu(settings.replace(onboarded=True))
        await show_screen(query, text, markup)
        await query.answer("Готово! Фильтры сохранены ✅")
        return

    await _rerender(query, step, settings, callback_data.ctx)
    await query.answer()


# --- Переключение пунктов фильтра ----------------------------------------


@wizard_router.callback_query(ToggleAction.filter(F.kind == "soon"))
async def on_soon(query: CallbackQuery, callback_data: ToggleAction) -> None:
    """Площадка есть в реестре, но парсера ещё нет."""
    await query.answer("Эта биржа скоро появится", show_alert=True)


@wizard_router.callback_query(ToggleAction.filter())
async def on_toggle(
    query: CallbackQuery,
    callback_data: ToggleAction,
    db: Database,
    access: AccessControl,
) -> None:
    if not await access.has_access(query.from_user.id):
        await query.answer("Нет доступа", show_alert=True)
        return

    settings = await db.get_user_settings(query.from_user.id)
    kind = callback_data.kind

    if kind == "src":
        updated = settings.toggled_source(callback_data.value)
        step = "sources"
    elif kind == "cat":
        category = _index(callback_data.value, CATEGORIES)
        if category is None:
            await query.answer()
            return
        updated = settings.toggled_category(category)
        step = "categories"
    elif kind == "kw":
        keyword = _index(callback_data.value, KEYWORD_PRESETS)
        if keyword is None:
            await query.answer()
            return
        updated = settings.toggled_keyword(keyword)
        step = "keywords"
    else:
        await query.answer()
        return

    await db.save_user_settings(query.from_user.id, updated)
    await _rerender(query, step, updated, callback_data.ctx)
    await query.answer()


@wizard_router.callback_query(BudgetAction.filter())
async def on_budget(
    query: CallbackQuery,
    callback_data: BudgetAction,
    db: Database,
    access: AccessControl,
) -> None:
    if not await access.has_access(query.from_user.id):
        await query.answer("Нет доступа", show_alert=True)
        return

    settings = await db.get_user_settings(query.from_user.id)
    updated = settings.replace(min_budget=callback_data.value)
    await db.save_user_settings(query.from_user.id, updated)
    await _rerender(query, "budget", updated, callback_data.ctx)
    await query.answer()


# --- Свои ключевые слова (единственный текстовый ввод) --------------------


@wizard_router.message(WizardStates.keywords)
async def on_keywords_text(
    message: Message,
    db: Database,
    access: AccessControl,
    state: FSMContext,
) -> None:
    if not await access.has_access(message.from_user.id if message.from_user else None):
        await state.clear()
        return

    data = await state.get_data()
    ctx = data.get("ctx", CTX_WIZARD)
    await state.clear()

    settings = await db.get_user_settings(message.from_user.id)
    updated = settings.with_keywords_added(message.text or "")
    await db.save_user_settings(message.from_user.id, updated)

    if ctx == CTX_SETTINGS:
        text, markup = render_settings(updated)
    else:
        text, markup = render_step("keywords", updated, CTX_WIZARD)
    await message.answer(text, reply_markup=markup)

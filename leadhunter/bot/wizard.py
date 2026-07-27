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

from bot import texts
from bot.access import AccessControl
from bot.callbacks import (
    CTX_SETTINGS,
    CTX_WIZARD,
    BudgetAction,
    SourceAction,
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
from core.sources import SOURCES, get_source, source_label
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
    query: CallbackQuery,
    step: str,
    settings: UserSettings,
    ctx: str,
    *,
    active: set[str] | None = None,
    blocked: set[str] | None = None,
) -> None:
    text, markup = render_step(step, settings, ctx, active=active, blocked=blocked)
    await show_screen(query, text, markup)


async def apply_sources(
    query: CallbackQuery, db: Database, ctx: str, supervisor
) -> None:
    """Перерисовывает экран «Биржи» по факту: что реально опрашивается.

    Сверку состава парсеров запускаем сразу, а не ждём фонового прохода —
    иначе включённая биржа начинала бы работать с задержкой, и на экране была
    бы неправда.
    """
    active: set[str] | None = None
    blocked: set[str] | None = None
    if supervisor is not None:
        try:
            await supervisor.reconcile()
            active, blocked = supervisor.active, supervisor.blocked
        except Exception:  # noqa: BLE001 — сбой сверки не должен ломать экран
            log.exception("Не удалось согласовать состав парсеров")
    settings = await db.get_user_settings(query.from_user.id)
    await _rerender(query, "sources", settings, ctx, active=active, blocked=blocked)


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
        await query.answer(texts.ERR_NO_ACCESS, show_alert=True)
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
        done = settings.replace(onboarded=True)
        text, markup = render_menu(done, await db.user_stats(query.from_user.id))
        await show_screen(query, text, markup)
        await query.answer("Готово! Фильтры сохранены ✅")
        return

    await _rerender(query, step, settings, callback_data.ctx)
    await query.answer()


# --- Переключение пунктов фильтра ----------------------------------------


@wizard_router.callback_query(ToggleAction.filter(F.kind == "soon"))
async def on_soon(query: CallbackQuery, callback_data: ToggleAction) -> None:
    """Площадка есть в реестре, но парсера нет — объясняем, почему."""
    source = get_source(callback_data.value)
    note = source.note if source and source.note else ""
    await query.answer(
        f"{texts.SOURCE_SOON}\n\n{note}" if note else texts.SOURCE_SOON,
        show_alert=True,
    )


@wizard_router.callback_query(ToggleAction.filter())
async def on_toggle(
    query: CallbackQuery,
    callback_data: ToggleAction,
    db: Database,
    access: AccessControl,
    sources=None,
) -> None:
    if not await access.has_access(query.from_user.id):
        await query.answer(texts.ERR_NO_ACCESS, show_alert=True)
        return

    settings = await db.get_user_settings(query.from_user.id)
    kind = callback_data.kind

    if kind == "src":
        # Источники хранятся отдельной таблицей: пишем туда и перечитываем.
        enabled = await db.toggle_source(query.from_user.id, callback_data.value)
        await apply_sources(query, db, callback_data.ctx, sources)
        label = source_label(callback_data.value)
        await query.answer(
            f"{label}: включена — начинаем опрос" if enabled
            else f"{label}: выключена — запросов к сайту больше нет"
        )
        return
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


@wizard_router.callback_query(SourceAction.filter())
async def on_source_action(
    query: CallbackQuery,
    callback_data: SourceAction,
    db: Database,
    access: AccessControl,
    sources=None,
) -> None:
    """«Выбрать все» / «Отключить все» / «🔄 Проверить сейчас» по бирже."""
    if not await access.has_access(query.from_user.id):
        await query.answer(texts.ERR_NO_ACCESS, show_alert=True)
        return

    user_id = query.from_user.id
    action = callback_data.action

    if action in ("all", "none"):
        enable = action == "all"
        for source in SOURCES:
            if source.available:
                await db.set_source_enabled(user_id, source.id, enable)
        await apply_sources(query, db, callback_data.ctx, sources)
        await query.answer(
            "Включены все биржи" if enable else "Все биржи выключены — опроса не будет"
        )
        return

    if action != "poll":
        await query.answer()
        return

    await query.answer(await _poll_source(callback_data.value, sources), show_alert=True)


async def _poll_source(source_id: str, supervisor) -> str:
    """Внеочередной опрос биржи. Возвращает текст для всплывающего окна."""
    source = get_source(source_id)
    label = source.label if source else source_id

    if supervisor is None:
        return texts.SOURCE_CHECK_OFFLINE
    if source_id not in supervisor.active:
        need = (
            f"\n\nНужен {source.needs} в .env" if source and source.needs else ""
        )
        return f"⚠️ {label}: опрос не идёт.{need}"

    try:
        found = await supervisor.poll_now(source_id)
    except Exception as exc:  # noqa: BLE001 — показываем настоящую причину
        log.warning("Внеочередной опрос %s не удался: %s", source_id, exc)
        return f"⚠️ {label}: биржа не ответила.\n\n{exc}"

    if found is None:
        return f"{label}: биржа опрашивается по расписанию, проверка вручную недоступна."
    return (
        f"✅ {label}: найдено новых заказов — {found}.\n\n"
        "Подходящие под твои фильтры придут карточками."
    )


@wizard_router.callback_query(BudgetAction.filter())
async def on_budget(
    query: CallbackQuery,
    callback_data: BudgetAction,
    db: Database,
    access: AccessControl,
) -> None:
    if not await access.has_access(query.from_user.id):
        await query.answer(texts.ERR_NO_ACCESS, show_alert=True)
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

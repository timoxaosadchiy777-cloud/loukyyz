"""Инлайн-клавиатуры бота."""

from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.callbacks import (
    CTX_SETTINGS,
    CTX_WIZARD,
    BudgetAction,
    CrmAction,
    EditAction,
    MenuAction,
    OrderAction,
    ToggleAction,
    WizardAction,
)
from core.models import CRM_LABELS, CrmStatus
from core.sources import SOURCES
from core.user_settings import BUDGET_PRESETS, CATEGORIES, KEYWORD_PRESETS, UserSettings

# Порядок кнопок воронки под карточкой (NEW — стартовый статус, кнопки нет).
_CRM_FLOW = (
    CrmStatus.CONTACTED,
    CrmStatus.NEGOTIATION,
    CrmStatus.WON,
    CrmStatus.LOST,
)

# Порядок шагов мастера. Кнопка «Далее» ведёт к следующему, «Назад» — к предыдущему.
WIZARD_STEPS: tuple[str, ...] = ("sources", "categories", "keywords", "budget")


def _mark(selected: bool) -> str:
    return "✅" if selected else "▫️"


def order_keyboard(
    order_id: int, crm_status: str = CrmStatus.NEW, saved: bool = False
) -> InlineKeyboardMarkup:
    """Клавиатура под карточкой: отклик, личные действия и воронка CRM.

    Все действия персональные: сохранение, правка отклика и статус воронки
    пишутся в доставку этого пользователя и других получателей не задевают.
    Текущий статус помечается точкой и не дублируется отдельной кнопкой.
    """
    builder = InlineKeyboardBuilder()
    builder.button(
        text="📋 Скопировать отклик",
        callback_data=OrderAction(action="copy", order_id=order_id),
    )
    builder.button(
        text="💔 Убрать из сохранённых" if saved else "❤️ Сохранить",
        callback_data=OrderAction(action="unsave" if saved else "save", order_id=order_id),
    )
    builder.button(
        text="✍️ Изменить отклик",
        callback_data=OrderAction(action="rewrite", order_id=order_id),
    )
    builder.button(
        text="❌ Отклонить",
        callback_data=OrderAction(action="reject", order_id=order_id),
    )
    for status in _CRM_FLOW:
        label = CRM_LABELS[status]
        if status == crm_status:
            label = f"• {label}"
        builder.button(
            text=label,
            callback_data=CrmAction(status=status, order_id=order_id),
        )
    # Отклик и сохранение сверху, затем правка/отклонение, затем воронка.
    builder.adjust(1, 1, 2, 2, 2)
    return builder.as_markup()


def rewrite_keyboard(order_id: int) -> InlineKeyboardMarkup:
    """Экран правки отклика: перегенерировать через ИИ или написать свой."""
    builder = InlineKeyboardBuilder()
    builder.button(
        text="🔄 Сгенерировать заново",
        callback_data=OrderAction(action="regen", order_id=order_id),
    )
    builder.button(
        text="◀️ Отмена",
        callback_data=OrderAction(action="cancel_rewrite", order_id=order_id),
    )
    builder.adjust(1, 1)
    return builder.as_markup()


# --- Панель управления ----------------------------------------------------


def menu_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="⚙️ Настройки", callback_data=MenuAction(action="settings"))
    builder.button(text="🔍 Проверить сейчас", callback_data=MenuAction(action="check"))
    builder.button(text="⭐ Сохранённые лиды", callback_data=MenuAction(action="saved"))
    builder.button(text="🌐 Биржи", callback_data=MenuAction(action="sources"))
    builder.adjust(2, 2)
    return builder.as_markup()


def settings_keyboard() -> InlineKeyboardMarkup:
    """Экран настроек: правка каждого фильтра по отдельности."""
    builder = InlineKeyboardBuilder()
    builder.button(text="🌐 Биржи", callback_data=EditAction(field="sources"))
    builder.button(text="🏷 Категории", callback_data=EditAction(field="categories"))
    builder.button(text="🔑 Ключевые слова", callback_data=EditAction(field="keywords"))
    builder.button(text="💰 Бюджет", callback_data=EditAction(field="budget"))
    builder.button(text="◀️ В меню", callback_data=MenuAction(action="menu"))
    builder.adjust(2, 2, 1)
    return builder.as_markup()


# --- Экраны выбора фильтров (общие для мастера и настроек) ----------------


def _navigation(builder: InlineKeyboardBuilder, step: str, ctx: str) -> tuple[int, ...]:
    """Дорисовывает навигацию и возвращает раскладку последних рядов."""
    if ctx == CTX_SETTINGS:
        builder.button(text="◀️ К настройкам", callback_data=MenuAction(action="settings"))
        return (1,)

    index = WIZARD_STEPS.index(step)
    if index > 0:
        builder.button(
            text="◀️ Назад",
            callback_data=WizardAction(step=WIZARD_STEPS[index - 1], ctx=CTX_WIZARD),
        )
    is_last = index == len(WIZARD_STEPS) - 1
    builder.button(
        text="✅ Готово" if is_last else "Далее ▶️",
        callback_data=WizardAction(
            step="done" if is_last else WIZARD_STEPS[index + 1], ctx=CTX_WIZARD
        ),
    )
    return (2,) if index > 0 else (1,)


def sources_keyboard(settings: UserSettings, ctx: str = CTX_WIZARD) -> InlineKeyboardMarkup:
    """Биржи. Недоступные показываем неактивными — место под Kwork занято заранее."""
    builder = InlineKeyboardBuilder()
    rows: list[int] = []
    for source in SOURCES:
        if not source.available:
            # Кнопка-заглушка: сообщает, что площадка в планах, и ничего не меняет.
            builder.button(
                text=f"🔜 {source.button_label}",
                callback_data=ToggleAction(kind="soon", value=source.id, ctx=ctx),
            )
        else:
            builder.button(
                text=f"{_mark(settings.source_enabled(source.id))} {source.label}",
                callback_data=ToggleAction(kind="src", value=source.id, ctx=ctx),
            )
        rows.append(1)
    return _finish(builder, rows, _navigation(builder, "sources", ctx))


def categories_keyboard(settings: UserSettings, ctx: str = CTX_WIZARD) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for index, category in enumerate(CATEGORIES):
        builder.button(
            text=f"{_mark(category in settings.categories)} {category}",
            callback_data=ToggleAction(kind="cat", value=str(index), ctx=ctx),
        )
    rows = [2] * ((len(CATEGORIES) + 1) // 2)
    return _finish(builder, rows, _navigation(builder, "categories", ctx))


def keywords_keyboard(settings: UserSettings, ctx: str = CTX_WIZARD) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for index, keyword in enumerate(KEYWORD_PRESETS):
        builder.button(
            text=f"{_mark(keyword in settings.keywords)} {keyword}",
            callback_data=ToggleAction(kind="kw", value=str(index), ctx=ctx),
        )
    rows = [3] * ((len(KEYWORD_PRESETS) + 2) // 3)
    builder.button(
        text="✏️ Добавить свои",
        callback_data=WizardAction(step="kw_input", ctx=ctx),
    )
    rows.append(1)
    return _finish(builder, rows, _navigation(builder, "keywords", ctx))


def budget_keyboard(settings: UserSettings, ctx: str = CTX_WIZARD) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for value in BUDGET_PRESETS:
        label = "без ограничения" if value == 0 else f"от {value}$"
        builder.button(
            text=f"{_mark(settings.min_budget == value)} {label}",
            callback_data=BudgetAction(value=value, ctx=ctx),
        )
    rows = [2] * ((len(BUDGET_PRESETS) + 1) // 2)
    return _finish(builder, rows, _navigation(builder, "budget", ctx))


def back_to_menu_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="◀️ В меню", callback_data=MenuAction(action="menu"))
    return builder.as_markup()


def _finish(
    builder: InlineKeyboardBuilder, rows: list[int], nav_rows: tuple[int, ...]
) -> InlineKeyboardMarkup:
    builder.adjust(*rows, *nav_rows)
    return builder.as_markup()

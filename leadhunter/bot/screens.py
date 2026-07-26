"""Отрисовка экранов панели: текст + клавиатура.

Вынесено из обработчиков, чтобы экраны можно было проверять тестами без
Telegram. Экраны выбора фильтров одни и те же для мастера онбординга и для
правки из настроек — различается только навигация (см. ``ctx``).
"""

from __future__ import annotations

from html import escape

from aiogram.types import InlineKeyboardMarkup

from bot.callbacks import CTX_WIZARD
from bot.keyboards import (
    WIZARD_STEPS,
    budget_keyboard,
    categories_keyboard,
    keywords_keyboard,
    menu_keyboard,
    settings_keyboard,
    sources_keyboard,
)
from core.models import Order
from core.user_settings import UserSettings

# Сколько лидов показываем в списках («Проверить сейчас», «Сохранённые»).
LEADS_LIMIT = 10

_STEP_TITLES: dict[str, str] = {
    "sources": "🌐 Биржи",
    "categories": "🏷 Категории",
    "keywords": "🔑 Ключевые слова",
    "budget": "💰 Минимальный бюджет",
}

_STEP_HINTS: dict[str, str] = {
    "sources": (
        "Отметь площадки, с которых нужны заказы.\n"
        "Если не отмечено ничего — присылаем со всех доступных."
    ),
    "categories": (
        "Что тебе интересно? Отметь подходящее.\n"
        "Ничего не отмечено — присылаем любые категории."
    ),
    "keywords": (
        "Слова, по которым ловим заказы (ищем в названии и описании).\n"
        "Можно добавить свои — кнопка ниже. Пусто — ловим всё."
    ),
    "budget": (
        "Заказы дешевле указанной суммы приходить не будут.\n"
        "Лиды без явного бюджета проходят всегда — там сумма обсуждается в чате."
    ),
}

_KEYBOARDS = {
    "sources": sources_keyboard,
    "categories": categories_keyboard,
    "keywords": keywords_keyboard,
    "budget": budget_keyboard,
}


def render_step(
    step: str, settings: UserSettings, ctx: str = CTX_WIZARD
) -> tuple[str, InlineKeyboardMarkup]:
    """Экран выбора одного фильтра."""
    title = _STEP_TITLES[step]
    if ctx == CTX_WIZARD:
        number = WIZARD_STEPS.index(step) + 1
        header = f"<b>Шаг {number}/{len(WIZARD_STEPS)} — {title}</b>"
    else:
        header = f"<b>{title}</b>"
    return f"{header}\n\n{_STEP_HINTS[step]}", _KEYBOARDS[step](settings, ctx)


def render_wizard_intro() -> str:
    return (
        "👋 <b>Настроим бота под тебя</b>\n\n"
        "Четыре быстрых шага: биржи, категории, ключевые слова и бюджет.\n"
        "Любой шаг можно пропустить — тогда фильтр не применяется."
    )


def render_menu(settings: UserSettings) -> tuple[str, InlineKeyboardMarkup]:
    lines = ["🎯 <b>LeadHunter</b>", "", "<b>Твои фильтры:</b>"]
    lines += [escape(line) for line in settings.summary_lines()]
    return "\n".join(lines), menu_keyboard()


def render_settings(settings: UserSettings) -> tuple[str, InlineKeyboardMarkup]:
    lines = ["⚙️ <b>Настройки</b>", ""]
    lines += [escape(line) for line in settings.summary_lines()]
    lines += ["", "Выбери, что изменить."]
    return "\n".join(lines), settings_keyboard()


def render_keywords_prompt(settings: UserSettings) -> str:
    current = ", ".join(settings.keywords) or "пока пусто"
    return (
        "✏️ <b>Свои ключевые слова</b>\n\n"
        "Пришли их одним сообщением через запятую.\n"
        "Например: <code>парсинг, автоматизация, google sheets</code>\n\n"
        f"Сейчас: {escape(current)}"
    )


# --- Списки лидов ---------------------------------------------------------


def _lead_line(row) -> str:
    order = Order.from_row(row)
    score = "н/д" if order.score is None else str(order.score)
    budget = order.budget_raw or (
        f"${order.budget_value}" if order.budget_value is not None else "не указан"
    )
    return (
        f'🔹 <a href="{escape(order.url)}">{escape(order.title)}</a>\n'
        f"    AI {escape(score)} · 💰 {escape(budget)} · "
        f"🗂 {escape(order.category or '—')}"
    )


def render_leads(rows, *, title: str, empty: str) -> str:
    if not rows:
        return f"<b>{title}</b>\n\n{empty}"
    lines = [f"<b>{title}</b>", ""]
    lines += [_lead_line(row) for row in rows]
    return "\n".join(lines)


def filter_orders(rows, settings: UserSettings, limit: int = LEADS_LIMIT) -> list:
    """Отбирает из свежих лидов те, что проходят персональные фильтры."""
    matched = [row for row in rows if settings.matches(Order.from_row(row))]
    return matched[:limit]

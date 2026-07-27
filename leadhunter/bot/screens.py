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
from bot.cards import TELEGRAM_LIMIT
from core.models import Order
from core.sources import SOURCES
from core.user_settings import UserSettings

# Сколько лидов показываем в списках («Проверить сейчас», «Сохранённые»).
LEADS_LIMIT = 10

# Запас под служебную разметку сообщения.
_SAFETY = 200

_STEP_TITLES: dict[str, str] = {
    "sources": "🌐 Биржи",
    "categories": "🏷 Категории",
    "keywords": "🔑 Ключевые слова",
    "budget": "💰 Минимальный бюджет",
}

_STEP_HINTS: dict[str, str] = {
    "sources": (
        "Отметь биржи, с которых нужны заказы.\n"
        "Выключенная биржа не опрашивается — запросов к сайту не будет.\n\n"
        "🟢 включена · ⚪ выключена · 🔴 нет парсера"
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

# «Биржи» строятся отдельно (см. render_step): у них своя раскладка с кнопками
# проверки и предупреждениями о неработающих площадках.
_KEYBOARDS = {
    "categories": categories_keyboard,
    "keywords": keywords_keyboard,
    "budget": budget_keyboard,
}


def render_step(
    step: str,
    settings: UserSettings,
    ctx: str = CTX_WIZARD,
    *,
    active: set[str] | None = None,
    blocked: set[str] | None = None,
) -> tuple[str, InlineKeyboardMarkup]:
    """Экран выбора одного фильтра.

    Args:
        active: Биржи, которые опрашиваются прямо сейчас (от супервизора
            парсеров). Нужны только экрану «Биржи»: по ним видно, что включённая
            площадка не поднялась, и чего ей не хватает.
        blocked: Биржи, запрещённые владельцем в ``settings.yaml``.
    """
    title = _STEP_TITLES[step]
    if ctx == CTX_WIZARD:
        number = WIZARD_STEPS.index(step) + 1
        header = f"<b>Шаг {number}/{len(WIZARD_STEPS)} — {title}</b>"
    else:
        header = f"<b>{title}</b>"

    body = _STEP_HINTS[step]
    if step == "sources":
        # Проверку «сейчас» показываем только в настройках: в мастере проверять
        # ещё нечего, фильтры не сохранены.
        keyboard = sources_keyboard(settings, ctx, with_poll=ctx != CTX_WIZARD)
        warning = _sources_warning(settings, active, blocked or set())
        if warning:
            body = f"{body}\n\n{warning}"
    else:
        keyboard = _KEYBOARDS[step](settings, ctx)
    return f"{header}\n\n{body}", keyboard


def _sources_warning(
    settings: UserSettings, active: set[str] | None, blocked: set[str]
) -> str:
    """Предупреждение о биржах, которые включены, но не опрашиваются.

    Молчаливо неработающий источник — худший из возможных: человек ждёт лидов,
    которых не будет. Поэтому пишем прямо, чего не хватает.
    """
    if active is None:
        return ""

    lines: list[str] = []
    for source in SOURCES:
        if not source.available or not settings.source_enabled(source.id):
            continue
        if source.id in active:
            continue
        if source.id in blocked:
            reason = "выключена владельцем в settings.yaml"
        elif source.needs:
            reason = f"нужен <code>{escape(source.needs)}</code> в .env"
        else:
            reason = "парсер не запущен"
        lines.append(f"⚠️ {escape(source.label)}: опрос не идёт — {reason}")
    return "\n".join(lines)


def render_wizard_intro() -> str:
    return (
        "👋 <b>Настроим бота под тебя</b>\n\n"
        "Четыре быстрых шага: биржи, категории, ключевые слова и бюджет.\n"
        "Любой шаг можно пропустить — тогда фильтр не применяется."
    )


def render_menu(
    settings: UserSettings, stats: tuple[int, int] | None = None
) -> tuple[str, InlineKeyboardMarkup]:
    lines = ["🎯 <b>LeadHunter</b>"]
    if stats is not None:
        received, saved = stats
        lines += ["", f"📊 Получено лидов: <b>{received}</b> · ❤️ Сохранено: <b>{saved}</b>"]
    lines += ["", "<b>Твои фильтры</b>"]
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
    # Десять лидов с длинными заголовками способны перерасти лимит Telegram,
    # и тогда сообщение не отправится вовсе. Добираем, пока влезает.
    budget = TELEGRAM_LIMIT - _SAFETY - len(lines[0])
    shown = 0
    for row in rows:
        line = _lead_line(row)
        if budget - len(line) - 1 < 0:
            break
        lines.append(line)
        budget -= len(line) + 1
        shown += 1
    if shown < len(rows):
        lines.append(f"\n… и ещё {len(rows) - shown}")
    return "\n".join(lines)


def filter_orders(rows, settings: UserSettings, limit: int = LEADS_LIMIT) -> list:
    """Отбирает из свежих лидов те, что проходят персональные фильтры."""
    matched = [row for row in rows if settings.matches(Order.from_row(row))]
    return matched[:limit]

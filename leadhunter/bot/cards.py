"""Форматирование карточек заказов (HTML для Telegram).

Карточка показывает название, бюджет, AI Score, категорию, причину («Почему
подходит»), вероятность сделки, статус воронки (CRM) и готовый отклик.
"""

from __future__ import annotations

from html import escape

from core.models import CRM_LABELS, CrmStatus, Order

_DIVIDER = "━━━━━━━━━━━━━━━━━━━━━"

# Telegram отклоняет сообщения длиннее 4096 символов. Раньше карточка с длинным
# откликом (AI_MAX_TOKENS до 1024 токенов) выходила за лимит, send_message падал,
# ошибка гасилась в рассылке — и платный клиент молча НЕ получал лид, причём
# доставка уже была отмечена, так что повторно лид не приходил.
TELEGRAM_LIMIT = 4096
_SAFETY_MARGIN = 64
_ELLIPSIS = "…"

# Потолки на отдельные поля: не дают одному раздутому полю съесть всю карточку.
_MAX_TITLE = 200
_MAX_REASON = 400
_MAX_SUMMARY = 300


def _cut(text: str, limit: int) -> str:
    """Обрезает по словам, чтобы не рвать слово посередине."""
    if len(text) <= limit:
        return text
    clipped = text[: max(0, limit - 1)]
    space = clipped.rfind(" ")
    if space > limit // 2:
        clipped = clipped[:space]
    return clipped.rstrip() + _ELLIPSIS

_SOURCE_LABELS = {
    "upwork": "Upwork",
    "fiverr": "Fiverr",
    "rss": "RSS",
    "kwork": "Kwork",
}


def _format_budget(order: Order) -> str:
    if order.budget_raw:
        return order.budget_raw
    if order.budget_value is not None:
        return f"${order.budget_value:,}".replace(",", " ")
    return "не указан"


def _score_emoji(score: int) -> str:
    if score >= 80:
        return "🟢"
    if score >= 60:
        return "🟡"
    return "🔴"


def _score_block(order: Order) -> list[str]:
    """Блок AI-оценки: score, категория, причина, вероятность сделки."""
    if order.score is None:
        lines = ["🤖 <b>AI Score:</b> н/д — оцените вручную"]
        if order.reason:
            lines.append(f"📊 Почему: {escape(order.reason)}")
        return lines

    lines = [
        f"{_score_emoji(order.score)} <b>AI Score:</b> {order.score}/100",
        f"🗂 Категория: {escape(order.category or '—')}",
    ]
    if order.technology:
        lines.append(f"🛠 Стек: {escape(order.technology)}")
    if order.summary:
        lines.append(f"📝 Суть: {escape(_cut(order.summary, _MAX_SUMMARY))}")
    if order.reason:
        lines.append(f"📊 Почему подходит: {escape(_cut(order.reason, _MAX_REASON))}")
    if order.probability_of_sale is not None:
        lines.append(f"📈 Вероятность сделки: {order.probability_of_sale}%")
    return lines


def _crm_line(crm_status: str) -> str:
    label = CRM_LABELS.get(crm_status, CRM_LABELS[CrmStatus.NEW])
    return f"📌 CRM-статус: <b>{escape(label)}</b>"


def render_card(order: Order, response: str) -> str:
    """Собирает HTML-карточку заказа для отправки владельцу."""
    source = _SOURCE_LABELS.get(order.source, order.source)
    budget = _format_budget(order)

    lines = [
        f"🎯 <b>{escape(_cut(order.title, _MAX_TITLE))}</b>",
        f"<i>Источник: {escape(source)}</i>",
        _DIVIDER,
        f"💰 Бюджет:  <code>{escape(budget)}</code>",
        *_score_block(order),
        _crm_line(order.crm_status),
        _DIVIDER,
        f"🔗 Ссылка:  <code>{escape(order.url)}</code>",
        _DIVIDER,
        "✍️ <b>Отклик:</b>",
    ]

    # Отклик — самая длинная и самая «резиновая» часть, поэтому под лимит
    # подгоняем именно его: заголовок, бюджет и оценка должны дойти целиком.
    head = "\n".join(lines)
    wrapper = "\n<blockquote></blockquote>"
    available = TELEGRAM_LIMIT - _SAFETY_MARGIN - len(head) - len(wrapper)
    body = _fit_escaped(response, available)
    return f"{head}\n<blockquote>{body}</blockquote>"


def _fit_escaped(text: str, available: int) -> str:
    """Готовит текст отклика так, чтобы экранированный вариант влез в лимит.

    Экранирование удлиняет строку (``&`` → ``&amp;``), поэтому режем исходный
    текст и проверяем длину уже после escape, а не до него — иначе на отклике
    с амперсандами лимит всё равно окажется превышен.
    """
    if available <= 0:
        return ""
    candidate = _cut(text, available)
    escaped = escape(candidate)
    while len(escaped) > available and len(candidate) > 1:
        candidate = _cut(candidate, int(len(candidate) * 0.9))
        escaped = escape(candidate)
    return escaped


def split_plain(text: str, limit: int = TELEGRAM_LIMIT) -> list[str]:
    """Режет длинный текст на части, влезающие в одно сообщение.

    Нужен там, где текст уходит без HTML-разметки (готовый отклик для
    копирования): обрезать его нельзя — пользователь должен получить отклик
    целиком, поэтому отдаём несколькими сообщениями.
    """
    if not text:
        return []
    parts: list[str] = []
    rest = text
    while len(rest) > limit:
        window = rest[:limit]
        # Режем по границе строки или слова, чтобы отклик оставался читаемым.
        cut = max(window.rfind("\n"), window.rfind(" "))
        if cut < limit // 2:
            cut = limit
        parts.append(rest[:cut].rstrip())
        rest = rest[cut:].lstrip()
    if rest:
        parts.append(rest)
    return parts

"""Форматирование карточек заказов (HTML для Telegram).

Карточка показывает AI Score, категорию, причину и вероятность соответствия,
статус воронки (CRM) и готовый отклик.
"""

from __future__ import annotations

from html import escape

from core.models import CRM_LABELS, CrmStatus, Order

_DIVIDER = "━━━━━━━━━━━━━━━━━━━━━"

_SOURCE_LABELS = {
    "upwork": "Upwork",
    "fiverr": "Fiverr",
    "rss": "RSS",
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


def _score_lines(order: Order) -> list[str]:
    """Блок AI-оценки: score, вероятность, категория, причина."""
    if order.score is None:
        lines = ["🤖 <b>AI Score:</b> н/д — оцените вручную"]
        if order.reason:
            lines.append(f"💬 {escape(order.reason)}")
        return lines

    lines = [
        f"{_score_emoji(order.score)} <b>AI Score:</b> {order.score}/100 "
        f"(вероятность {order.score}%)",
    ]
    if order.category:
        lines.append(f"🗂 Категория: {escape(order.category)}")
    if order.reason:
        lines.append(f"💬 {escape(order.reason)}")
    return lines


def _crm_line(crm_status: str) -> str:
    label = CRM_LABELS.get(crm_status, CRM_LABELS[CrmStatus.NEW])
    return f"📌 Статус: <b>{escape(label)}</b>"


def render_card(order: Order, response: str) -> str:
    """Собирает HTML-карточку заказа для отправки владельцу."""
    source = _SOURCE_LABELS.get(order.source, order.source)
    budget = _format_budget(order)

    lines = [
        f"🎯 <b>{escape(order.title)}</b>",
        f"<i>Источник: {escape(source)}</i>",
        _DIVIDER,
        *_score_lines(order),
        _DIVIDER,
        f"💰 Бюджет:  <code>{escape(budget)}</code>",
        f"🔗 Ссылка:  <code>{escape(order.url)}</code>",
        _crm_line(order.crm_status),
        _DIVIDER,
        "✍️ <b>Отклик:</b>",
        f"<blockquote>{escape(response)}</blockquote>",
    ]
    return "\n".join(lines)

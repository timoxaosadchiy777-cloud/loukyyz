"""Форматирование карточек заказов (HTML для Telegram).

Карточка показывает название, бюджет, AI Score, категорию, причину («Почему
подходит»), вероятность сделки, статус воронки (CRM) и готовый отклик.
"""

from __future__ import annotations

from html import escape

from core.models import CRM_LABELS, CrmStatus, Order

_DIVIDER = "━━━━━━━━━━━━━━━━━━━━━"

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
        lines.append(f"📝 Суть: {escape(order.summary)}")
    if order.reason:
        lines.append(f"📊 Почему подходит: {escape(order.reason)}")
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
        f"🎯 <b>{escape(order.title)}</b>",
        f"<i>Источник: {escape(source)}</i>",
        _DIVIDER,
        f"💰 Бюджет:  <code>{escape(budget)}</code>",
        *_score_block(order),
        _crm_line(order.crm_status),
        _DIVIDER,
        f"🔗 Ссылка:  <code>{escape(order.url)}</code>",
        _DIVIDER,
        "✍️ <b>Отклик:</b>",
        f"<blockquote>{escape(response)}</blockquote>",
    ]
    return "\n".join(lines)

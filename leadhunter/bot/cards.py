"""Форматирование карточек заказов (HTML для Telegram).

Чёткая иерархия, моноширинный шрифт для ссылок и бюджетов, аккуратные разделители.
"""

from __future__ import annotations

from html import escape

from core.models import Order

_DIVIDER = "━━━━━━━━━━━━━━━━━━━━━"

_SOURCE_LABELS = {
    "telegram": "Telegram",
    "kwork": "Kwork",
}


def _format_budget(order: Order) -> str:
    if order.budget_raw:
        return order.budget_raw
    if order.budget_value is not None:
        return f"{order.budget_value:,} ₽".replace(",", " ")
    return "не указан"


def render_card(order: Order, response: str) -> str:
    """Собирает HTML-карточку заказа для отправки владельцу."""
    source = _SOURCE_LABELS.get(order.source, order.source)
    budget = _format_budget(order)

    return "\n".join(
        [
            f"🎯 <b>{escape(order.title)}</b>",
            f"<i>Источник: {escape(source)}</i>",
            _DIVIDER,
            f"💰 Бюджет:  <code>{escape(budget)}</code>",
            f"🔗 Ссылка:  <code>{escape(order.url)}</code>",
            _DIVIDER,
            "✍️ <b>Отклик:</b>",
            f"<blockquote>{escape(response)}</blockquote>",
        ]
    )

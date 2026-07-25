"""Форматирование карточек заказов (HTML для Telegram)."""

from __future__ import annotations

from html import escape

from schemas.lead import LeadRead

_DIVIDER = "━━━━━━━━━━━━━━━━━━━━━"
_NO_RESPONSE = "(не удалось сгенерировать отклик — сформулируйте вручную)"


def _format_budget(lead: LeadRead) -> str:
    if lead.budget_raw:
        return lead.budget_raw
    if lead.budget_value is not None:
        return f"{lead.budget_value:,} ₽".replace(",", " ")
    return "не указан"


def render_card(lead: LeadRead, response: str | None) -> str:
    """Собирает HTML-карточку заказа для отправки владельцу."""
    return "\n".join(
        [
            f"🎯 <b>{escape(lead.title)}</b>",
            _DIVIDER,
            f"💰 Бюджет:  <code>{escape(_format_budget(lead))}</code>",
            f"🔗 Ссылка:  <code>{escape(lead.url)}</code>",
            _DIVIDER,
            "✍️ <b>Отклик:</b>",
            f"<blockquote>{escape(response or _NO_RESPONSE)}</blockquote>",
        ]
    )

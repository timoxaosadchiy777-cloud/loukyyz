"""Генератор откликов на базе Claude (Anthropic API).

Пишет короткий, жёсткий и профессиональный отклик-решение под ТЗ клиента —
без приветствий, вводных слов и клише.
"""

from __future__ import annotations

import logging

from anthropic import APIError, AsyncAnthropic

from config import Settings
from core.models import Order

log = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
Ты — senior-специалист, который откликается на фриланс-заказы. По тексту ТЗ \
напиши короткий, жёсткий и профессиональный отклик-решение.

Правила:
- Никаких приветствий и вводных слов («Здравствуйте», «Готов помочь», «Меня зовут»).
- Никаких клише и воды («имею большой опыт», «качественно и в срок», «обращайтесь»).
- Сразу по сути: покажи, что понял задачу, и предложи конкретное решение/подход.
- Укажи ключевой стек или шаги реализации, если это уместно.
- Один сильный уточняющий вопрос — только если без него нельзя оценить работу.
- Тон уверенный и компетентный, без лести и без самоуничижения.
- Объём: 3–6 предложений. Пиши на языке заказа (по умолчанию — русский).
- Верни только текст отклика, без пояснений и разметки.
"""


class Responder:
    """Оборачивает Claude API для генерации откликов."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        # Пустой api_key => SDK возьмёт ANTHROPIC_API_KEY / профиль из окружения.
        self._client = AsyncAnthropic(api_key=settings.anthropic_api_key or None)

    async def generate(self, order: Order) -> str | None:
        """Возвращает текст отклика или ``None`` при ошибке/отказе."""
        if not self._settings.anthropic_ready:
            log.warning("ANTHROPIC_API_KEY не задан — отклик не сгенерирован")
            return None

        user_content = (
            f"Заголовок заказа:\n{order.title}\n\n"
            f"Текст ТЗ:\n{order.description.strip()}"
        )

        request: dict = {
            "model": self._settings.anthropic_model,
            "max_tokens": self._settings.anthropic_max_tokens,
            "system": SYSTEM_PROMPT,
            "messages": [{"role": "user", "content": user_content}],
            "output_config": {"effort": self._settings.anthropic_effort},
        }
        # Адаптивное мышление повышает качество отклика; управляется через .env.
        if self._settings.anthropic_thinking:
            request["thinking"] = {"type": "adaptive"}

        try:
            response = await self._client.messages.create(**request)
        except APIError as exc:
            log.error("Ошибка Claude API для %s: %s", order.dedup_key, exc)
            return None

        if response.stop_reason == "refusal":
            log.warning("Claude отказался отвечать по заказу %s", order.dedup_key)
            return None

        text = "".join(
            block.text for block in response.content if block.type == "text"
        ).strip()
        return text or None

    async def aclose(self) -> None:
        await self._client.close()

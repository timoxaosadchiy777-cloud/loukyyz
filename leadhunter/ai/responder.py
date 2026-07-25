"""Генератор откликов на базе абстрактного слоя LLM.

Пишет короткий, жёсткий и профессиональный отклик-решение под ТЗ клиента —
без приветствий, вводных слов и клише. Модель/провайдер задаётся через
:mod:`ai.llm` (по умолчанию Google Gemini), поэтому здесь — только промпт и
сборка запроса, без привязки к конкретному SDK.
"""

from __future__ import annotations

import logging

from ai.llm import LLMClient
from config import Settings
from core.models import Order

log = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
You are a senior freelancer writing a proposal in reply to a job post. Write a \
short, sharp, professional proposal that convinces an international client to \
hire you.

Rules:
- Write in English. If the job post is clearly written in another language, \
reply in that language instead.
- No greetings or filler ("Hello", "I hope you're well", "I'm excited to..."). \
No clichés ("I have great experience", "high quality and on time", "feel free \
to reach out").
- Open by showing you understood the task, then propose a concrete approach or \
solution.
- Mention the key stack or the concrete steps when it's relevant.
- Add one strong clarifying question only if it's genuinely needed to scope the \
work.
- Confident, competent tone. No flattery, no self-deprecation.
- 3–6 sentences. Return only the proposal text — no preamble, no markdown, no \
subject line.
"""


class Responder:
    """Генерирует отклики через инъецированный :class:`LLMClient`."""

    def __init__(self, llm: LLMClient, settings: Settings) -> None:
        self._llm = llm
        self._settings = settings

    async def generate(self, order: Order) -> str | None:
        """Возвращает текст отклика или ``None`` при ошибке/отсутствии ключа."""
        user_content = (
            f"Job title:\n{order.title}\n\n"
            f"Job description:\n{order.description.strip()}"
        )
        return await self._llm.complete(
            system=SYSTEM_PROMPT,
            user=user_content,
            max_output_tokens=self._settings.gemini_max_tokens,
            temperature=self._settings.gemini_temperature,
            label=f"proposal:{order.dedup_key}",
        )

    async def aclose(self) -> None:
        await self._llm.aclose()

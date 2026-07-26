"""Генератор откликов на базе абстрактного слоя LLM.

Отклик строится с учётом трёх источников: (1) текста заказа, (2) профиля
исполнителя из `profile.md` и (3) AI-анализа заказа (категория и причина от
скоринга). Модель/провайдер задаётся через :mod:`ai.llm` (по умолчанию Google
Gemini), поэтому здесь — только промпт и сборка запроса, без привязки к SDK.
"""

from __future__ import annotations

import logging

from ai.llm import LLMClient
from ai.scoring import LeadScore
from config import Settings
from core.models import Order
from core.profile import ProfileLoader

log = logging.getLogger(__name__)

_SYSTEM_PROMPT = """\
You are the freelancer described in the profile below. Write a proposal replying \
to a job post, as yourself, drawing on the skills and experience in your profile.

Rules:
- Reply in the language of the job post (English if it's in English).
- No greetings or filler ("Hello", "I hope you're well", "I'm excited to..."). \
No clichés ("I have great experience", "high quality and on time").
- Open by showing you understood the specific task, then propose a concrete \
approach grounded in YOUR actual skills from the profile.
- Mention the relevant stack or concrete steps. Do not invent skills you don't \
have in the profile.
- Add one sharp clarifying question only if genuinely needed to scope the work.
- Confident, competent tone. 3–6 sentences. Return only the proposal text — no \
preamble, no markdown, no subject line.
"""


class Responder:
    """Генерирует отклики через инъецированный :class:`LLMClient`."""

    def __init__(self, llm: LLMClient, settings: Settings, profile: ProfileLoader) -> None:
        self._llm = llm
        self._settings = settings
        self._profile = profile

    async def generate(self, order: Order, analysis: LeadScore | None = None) -> str | None:
        """Возвращает текст отклика или ``None`` при ошибке/отсутствии ключа.

        Args:
            order: Заказ, на который пишем отклик.
            analysis: Результат AI-скоринга (категория/причина) — помогает модели
                сфокусировать отклик на том, почему заказ подходит.
        """
        system = self._build_system(self._profile.read())
        user = self._build_user(order, analysis)
        return await self._llm.complete(
            system=system,
            user=user,
            max_output_tokens=self._settings.gemini_max_tokens,
            temperature=self._settings.gemini_temperature,
            label=f"proposal:{order.dedup_key}",
        )

    @staticmethod
    def _build_system(profile: str) -> str:
        if not profile:
            return _SYSTEM_PROMPT
        return f"{_SYSTEM_PROMPT}\n\n## Your profile\n\n{profile}"

    @staticmethod
    def _build_user(order: Order, analysis: LeadScore | None) -> str:
        parts = [
            f"Job title:\n{order.title}",
            f"Job description:\n{order.description.strip()}",
        ]
        if order.budget_raw or order.budget_value is not None:
            budget = order.budget_raw or f"${order.budget_value}"
            parts.append(f"Budget: {budget}")
        if analysis is not None and analysis.available:
            # AI-анализ помогает модели опереться на выявленную суть заказа.
            parts.append(
                "AI analysis of this lead (use it to focus the proposal):\n"
                f"- category: {analysis.category}\n"
                f"- why it fits: {analysis.reason}"
            )
        return "\n\n".join(parts)

    async def aclose(self) -> None:
        await self._llm.aclose()

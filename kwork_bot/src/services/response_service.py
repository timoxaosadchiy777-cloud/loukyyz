"""Сервис генерации откликов (обёртка над GeminiClient + промпты)."""

from __future__ import annotations

from ai.gemini_client import GeminiClient
from ai.prompts import SYSTEM_PROMPT, build_user_content
from schemas.lead import LeadCreate


class ResponseService:
    """Генерирует текст отклика по заказу. Возвращает ``None`` при сбое ИИ."""

    def __init__(self, gemini: GeminiClient) -> None:
        self._gemini = gemini

    async def generate(self, lead: LeadCreate) -> str | None:
        user_content = build_user_content(lead.title, lead.description)
        return await self._gemini.generate(SYSTEM_PROMPT, user_content)

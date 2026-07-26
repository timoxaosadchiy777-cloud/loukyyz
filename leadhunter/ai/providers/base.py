"""Единый контракт AI-провайдера.

Провайдер получает готовый текстовый промпт и возвращает текст ответа модели.
Все различия API (OpenRouter, Groq, Ollama, Gemini) спрятаны внутри конкретных
реализаций; роутер (:mod:`ai.llm`) работает только через этот интерфейс.

Контракт по ошибкам: при любом сбое (нет ключа, лимит, недоступная модель, сеть)
провайдер бросает :class:`ProviderError` с человекочитаемой причиной — роутер
ловит её и переходит к следующему провайдеру.
"""

from __future__ import annotations

import abc


class ProviderError(Exception):
    """Ошибка провайдера — сигнал роутеру перейти к следующему.

    Attributes:
        provider: Имя провайдера, где произошла ошибка.
        reason: Короткая человекочитаемая причина (лимит/ключ/модель/сеть).
    """

    def __init__(self, provider: str, reason: str) -> None:
        self.provider = provider
        self.reason = reason
        super().__init__(f"{provider}: {reason}")


class AIProvider(abc.ABC):
    """Базовый класс всех AI-провайдеров."""

    #: Короткое имя для логов и диагностики (например, "OpenRouter").
    name: str = "base"

    @abc.abstractmethod
    def is_configured(self) -> bool:
        """Готов ли провайдер к работе (есть ключ/эндпоинт). Без сетевых вызовов."""
        raise NotImplementedError

    @abc.abstractmethod
    async def generate(
        self,
        prompt: str,
        *,
        json_mode: bool = False,
        max_tokens: int = 1024,
        temperature: float = 0.7,
    ) -> str:
        """Возвращает текст ответа модели на ``prompt``.

        Дополнительные параметры — опциональные (контракт остаётся
        ``generate(prompt) -> str``):

        Args:
            prompt: Полный текст запроса (система + пользователь склеены роутером).
            json_mode: Просить модель вернуть строго JSON (если API умеет).
            max_tokens: Ограничение длины ответа.
            temperature: «Разнообразие» ответа (0.0 — детерминированно).

        Raises:
            ProviderError: При любом сбое — роутер перейдёт к следующему провайдеру.
        """
        raise NotImplementedError

    async def aclose(self) -> None:
        """Освобождает ресурсы (HTTP-клиент и т.п.). По умолчанию — ничего."""
        return None

    # Описание модели/эндпоинта для диагностики (check_ai.py).
    def describe(self) -> str:
        return self.name

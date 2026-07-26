"""Groq — быстрый бесплатный провайдер (OpenAI-совместимый API).

Groq раздаёт бесплатный доступ к open-source моделям (Llama и др.) с очень низкой
задержкой. Ключ бесплатный: https://console.groq.com/keys
"""

from __future__ import annotations

from ai.providers._openai_chat import OpenAIChatProvider

_ENDPOINT = "https://api.groq.com/openai/v1/chat/completions"


class GroqProvider(OpenAIChatProvider):
    name = "Groq"
    endpoint = _ENDPOINT

    def __init__(self, api_key: str, model: str, *, timeout: float = 45.0) -> None:
        super().__init__(api_key, model, timeout=timeout)

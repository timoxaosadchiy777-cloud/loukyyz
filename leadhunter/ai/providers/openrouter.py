"""OpenRouter — основной провайдер (бесплатные модели).

OpenRouter даёт единый OpenAI-совместимый доступ к множеству моделей, включая
бесплатные (суффикс `:free`), напр. `deepseek/deepseek-chat:free`. Ключ бесплатный:
https://openrouter.ai/keys
"""

from __future__ import annotations

from ai.providers._openai_chat import OpenAIChatProvider

_ENDPOINT = "https://openrouter.ai/api/v1/chat/completions"


class OpenRouterProvider(OpenAIChatProvider):
    name = "OpenRouter"
    endpoint = _ENDPOINT

    def __init__(self, api_key: str, model: str, *, timeout: float = 45.0) -> None:
        super().__init__(
            api_key,
            model,
            # Необязательные заголовки OpenRouter (атрибуция приложения).
            extra_headers={
                "HTTP-Referer": "https://github.com/leadhunter",
                "X-Title": "LeadHunter",
            },
            timeout=timeout,
        )

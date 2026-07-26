"""Gemini — провайдер последней очереди (google-genai SDK, одна модель).

Оставлен как крайний fallback: если бесплатные провайдеры недоступны, а у вас есть
рабочий ключ Gemini. Внутреннего fallback на вторую модель здесь НЕТ — переключение
между провайдерами делает роутер (:mod:`ai.llm`).
"""

from __future__ import annotations

from google import genai
from google.genai import errors as genai_errors
from google.genai import types

from ai.providers.base import AIProvider, ProviderError


def _describe(exc: genai_errors.APIError) -> str:
    code = getattr(exc, "code", "?")
    status = getattr(exc, "status", "?")
    message = getattr(exc, "message", None) or str(exc)
    return f"code={code} status={status} message={message}"


class GeminiProvider(AIProvider):
    name = "Gemini"

    def __init__(self, api_key: str, model: str) -> None:
        self._api_key = api_key
        self._model = model
        self._client = genai.Client(api_key=api_key) if api_key else None

    def is_configured(self) -> bool:
        return bool(self._api_key and self._model)

    def describe(self) -> str:
        return f"{self.name} · {self._model}"

    async def generate(
        self,
        prompt: str,
        *,
        json_mode: bool = False,
        max_tokens: int = 1024,
        temperature: float = 0.7,
    ) -> str:
        if self._client is None:
            raise ProviderError(self.name, "нет GEMINI_API_KEY")

        config_kwargs = dict(max_output_tokens=max_tokens, temperature=temperature)
        if json_mode:
            config_kwargs["response_mime_type"] = "application/json"

        try:
            resp = await self._client.aio.models.generate_content(
                model=self._model,
                contents=prompt,
                config=types.GenerateContentConfig(**config_kwargs),
            )
        except genai_errors.APIError as exc:
            raise ProviderError(self.name, _describe(exc)) from exc
        except Exception as exc:  # noqa: BLE001
            raise ProviderError(self.name, f"{type(exc).__name__}: {exc}") from exc

        if not resp.candidates:
            raise ProviderError(self.name, "пустой ответ (фильтр)")
        try:
            text = (resp.text or "").strip()
        except Exception as exc:  # .text может бросать при блокировке фильтром
            raise ProviderError(self.name, f"ответ отфильтрован: {exc}") from exc
        if not text:
            raise ProviderError(self.name, "пустой ответ")
        return text

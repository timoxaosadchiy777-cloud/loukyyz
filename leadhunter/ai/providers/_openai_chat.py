"""Общая база для OpenAI-совместимых чат-провайдеров (OpenRouter, Groq).

Оба API принимают один и тот же формат `/chat/completions`, различаются только
эндпоинтом, ключом и заголовками — поэтому логика запроса живёт здесь, а
конкретные провайдеры лишь задают эти параметры.

response_format=json намеренно НЕ отправляется: часть бесплатных моделей его не
поддерживает и падает с 400. Строгий JSON обеспечивается промптом скоринга и
устойчивым разбором (`ai.scoring._parse_score`), а не флагом API.
"""

from __future__ import annotations

import httpx

from ai.providers.base import AIProvider, ProviderError


def _snippet(text: str, limit: int = 200) -> str:
    text = " ".join((text or "").split())
    return text[:limit]


class OpenAIChatProvider(AIProvider):
    """Провайдер поверх OpenAI-совместимого эндпоинта `/chat/completions`."""

    #: Полный URL эндпоинта чата (задаёт подкласс).
    endpoint: str = ""

    def __init__(
        self,
        api_key: str,
        model: str,
        *,
        extra_headers: dict[str, str] | None = None,
        timeout: float = 45.0,
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._extra_headers = extra_headers or {}
        self._timeout = timeout
        self._client: httpx.AsyncClient | None = None

    def is_configured(self) -> bool:
        return bool(self._api_key and self._model)

    def describe(self) -> str:
        return f"{self.name} · {self._model}"

    def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self._timeout)
        return self._client

    async def generate(
        self,
        prompt: str,
        *,
        json_mode: bool = False,
        max_tokens: int = 1024,
        temperature: float = 0.7,
    ) -> str:
        if not self.is_configured():
            raise ProviderError(self.name, "нет API-ключа или модели")

        payload = {
            "model": self._model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
            **self._extra_headers,
        }

        try:
            resp = await self._http().post(self.endpoint, headers=headers, json=payload)
        except httpx.HTTPError as exc:
            raise ProviderError(self.name, f"сеть: {exc}") from exc

        self._raise_for_status(resp)

        try:
            data = resp.json()
            text = data["choices"][0]["message"]["content"]
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise ProviderError(self.name, f"неожиданный ответ API: {exc}") from exc

        text = (text or "").strip()
        if not text:
            raise ProviderError(self.name, "пустой ответ")
        return text

    def _raise_for_status(self, resp: httpx.Response) -> None:
        code = resp.status_code
        if code < 400:
            return
        if code == 401:
            raise ProviderError(self.name, "неверный API-ключ (401)")
        if code == 402:
            raise ProviderError(self.name, "нужен платный план/кредиты (402)")
        if code == 404:
            raise ProviderError(self.name, f"модель недоступна (404): {self._model}")
        if code == 429:
            raise ProviderError(self.name, "лимит/квота исчерпаны (429)")
        raise ProviderError(self.name, f"HTTP {code}: {_snippet(resp.text)}")

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

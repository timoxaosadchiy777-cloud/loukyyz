"""Ollama — локальный провайдер (модели крутятся на своей машине, бесплатно).

Требует запущенного `ollama serve` и скачанной модели (`ollama pull llama3.2`).
По умолчанию ВЫКЛЮЧЕН (OLLAMA_ENABLED=false), чтобы роутер не стучался в
localhost, когда Ollama не установлен. Включите его в .env, если он у вас есть.
"""

from __future__ import annotations

import httpx

from ai.providers.base import AIProvider, ProviderError


class OllamaProvider(AIProvider):
    name = "Ollama"

    def __init__(
        self,
        host: str,
        model: str,
        *,
        enabled: bool = False,
        timeout: float = 120.0,
    ) -> None:
        self._host = (host or "http://localhost:11434").rstrip("/")
        self._model = model
        self._enabled = enabled
        self._timeout = timeout
        self._client: httpx.AsyncClient | None = None

    def is_configured(self) -> bool:
        # Локальный сервер: считаем «настроенным», только если явно включён.
        return bool(self._enabled and self._host and self._model)

    def describe(self) -> str:
        return f"{self.name} · {self._model} @ {self._host}"

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
        if not self._enabled:
            raise ProviderError(self.name, "выключен (OLLAMA_ENABLED=false)")

        payload = {
            "model": self._model,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": temperature, "num_predict": max_tokens},
        }
        if json_mode:
            payload["format"] = "json"

        try:
            resp = await self._http().post(f"{self._host}/api/generate", json=payload)
        except httpx.HTTPError as exc:
            raise ProviderError(self.name, f"локальный сервер недоступен: {exc}") from exc

        if resp.status_code == 404:
            raise ProviderError(self.name, f"модель не найдена — выполни: ollama pull {self._model}")
        if resp.status_code >= 400:
            raise ProviderError(self.name, f"HTTP {resp.status_code}: {resp.text[:200]}")

        try:
            text = (resp.json().get("response") or "").strip()
        except ValueError as exc:
            raise ProviderError(self.name, f"неожиданный ответ: {exc}") from exc

        if not text:
            raise ProviderError(self.name, "пустой ответ")
        return text

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

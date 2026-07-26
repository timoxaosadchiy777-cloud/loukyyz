"""Слой LLM: маршрутизация между AI-провайдерами с fallback.

LeadHunter больше не привязан к одному платному API. :class:`LLMRouter` перебирает
провайдеров по порядку (OpenRouter → Groq → Ollama → Gemini) и берёт первый, кто
ответил. Если провайдер не настроен, отдал ошибку, упёрся в лимит или у него нет
модели — роутер автоматически переходит к следующему.

Скоринг (:mod:`ai.scoring`) и генерация откликов (:mod:`ai.responder`) обращаются
к роутеру через тот же метод ``complete(...)``, что и раньше, — их код не менялся.
Провайдеры принимают единый текстовый промпт (`generate(prompt) -> str`), поэтому
роутер склеивает system+user в один промпт.
"""

from __future__ import annotations

import logging
from typing import Protocol, runtime_checkable

from ai.providers import AIProvider, ProviderError
from ai.providers.gemini import GeminiProvider
from ai.providers.groq import GroqProvider
from ai.providers.ollama import OllamaProvider
from ai.providers.openrouter import OpenRouterProvider
from config import Settings

log = logging.getLogger(__name__)

# Канонический порядок fallback (item: OpenRouter → Groq → Ollama → Gemini).
_ORDER = ("openrouter", "groq", "ollama", "gemini")


@runtime_checkable
class LLMClient(Protocol):
    """Контракт для скоринга/генерации. Реализация — :class:`LLMRouter`."""

    async def complete(
        self,
        *,
        system: str,
        user: str,
        max_output_tokens: int,
        temperature: float,
        json_mode: bool = False,
        label: str = "llm",
    ) -> str | None:
        ...

    async def aclose(self) -> None:
        ...


def _combine(system: str, user: str) -> str:
    """Склеивает системную инструкцию и запрос в единый промпт для провайдеров."""
    system = (system or "").strip()
    user = (user or "").strip()
    if not system:
        return user
    return f"{system}\n\n---\n\n{user}"


class LLMRouter:
    """Маршрутизатор AI-провайдеров с автоматическим fallback."""

    def __init__(self, providers: list[AIProvider]) -> None:
        self._providers = providers
        #: Имя провайдера, который ответил последним успешно.
        self.current_provider: str = ""
        #: Человекочитаемая причина последнего полного отказа (для Telegram/логов).
        self.last_error: str = ""

    def configured_names(self) -> list[str]:
        return [p.name for p in self._providers if p.is_configured()]

    async def complete(
        self,
        *,
        system: str,
        user: str,
        max_output_tokens: int,
        temperature: float,
        json_mode: bool = False,
        label: str = "llm",
    ) -> str | None:
        prompt = _combine(system, user)
        failures: list[str] = []

        for provider in self._providers:
            if not provider.is_configured():
                continue
            try:
                text = await provider.generate(
                    prompt,
                    json_mode=json_mode,
                    max_tokens=max_output_tokens,
                    temperature=temperature,
                )
            except ProviderError as exc:
                failures.append(f"{exc.provider}: {exc.reason}")
                log.error("AI ERROR (provider=%s, %s): %s", exc.provider, label, exc.reason)
                continue
            except Exception as exc:  # noqa: BLE001 — не роняем пайплайн
                failures.append(f"{provider.name}: {type(exc).__name__}: {exc}")
                log.error("AI ERROR (provider=%s, %s): %r", provider.name, label, exc, exc_info=True)
                continue

            self.current_provider = provider.name
            self.last_error = ""
            if failures:
                log.info("AI: ответ через %s (%s) после сбоев: %s", provider.name, label, "; ".join(failures))
            else:
                log.info("AI: ответ через %s (%s)", provider.name, label)
            return text

        self.last_error = "; ".join(failures) or "нет настроенных AI-провайдеров"
        log.error("AI ERROR (%s): все провайдеры недоступны — %s", label, self.last_error)
        return None

    async def aclose(self) -> None:
        for provider in self._providers:
            try:
                await provider.aclose()
            except Exception:  # noqa: BLE001
                pass


def _build_providers(settings: Settings) -> list[AIProvider]:
    """Создаёт провайдеров и упорядочивает: выбранный основной — первым."""
    catalog: dict[str, AIProvider] = {
        "openrouter": OpenRouterProvider(settings.openrouter_api_key, settings.openrouter_model),
        "groq": GroqProvider(settings.groq_api_key, settings.groq_model),
        "ollama": OllamaProvider(
            settings.ollama_host, settings.ollama_model, enabled=settings.ollama_enabled
        ),
        "gemini": GeminiProvider(settings.gemini_api_key, settings.gemini_model),
    }
    primary = (settings.ai_provider or "openrouter").strip().lower()
    order: list[str] = []
    if primary in catalog:
        order.append(primary)
    for name in _ORDER:
        if name not in order:
            order.append(name)
    return [catalog[name] for name in order]


def create_llm(settings: Settings) -> LLMRouter:
    """Фабрика роутера LLM: строит цепочку провайдеров и логирует диагностику."""
    router = LLMRouter(_build_providers(settings))
    configured = router.configured_names()
    log.info(
        "LLM роутер: провайдеры=[%s], настроены=[%s]",
        ", ".join(p.name for p in router._providers),
        ", ".join(configured) or "НЕТ — задай ключ в .env",
    )
    if not configured:
        log.error(
            "AI ERROR: ни один провайдер не настроен. Впиши хотя бы один ключ в .env "
            "(OPENROUTER_API_KEY / GROQ_API_KEY / GEMINI_API_KEY) или включи Ollama. "
            "Проверка: python check_ai.py"
        )
    return router

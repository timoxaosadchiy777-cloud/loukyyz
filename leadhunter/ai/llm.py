"""Слой LLM: маршрутизация между AI-провайдерами с fallback.

LeadHunter не привязан к одному платному API. :class:`LLMRouter` перебирает
провайдеров по порядку (OpenRouter → Groq → Ollama → Gemini) и берёт первого, кто
ответил. Если провайдер не настроен, отдал ошибку, упёрся в лимит или у него нет
модели — роутер автоматически переходит к следующему.

Важно (архитектура): провайдеры импортируются ЛЕНИВО, каждый в момент сборки
цепочки. У каждого свои зависимости (например, Gemini тянет `google-genai`), и
если пакет провайдера не установлен — этот провайдер просто пропускается, а не
роняет запуск всего приложения. Так Groq работает без установленного Gemini.

Скоринг (:mod:`ai.scoring`) и генерация откликов (:mod:`ai.responder`) обращаются
к роутеру через тот же метод ``complete(...)``, что и раньше, — их код не менялся.
"""

from __future__ import annotations

import importlib
import logging
from typing import Protocol, runtime_checkable

# Только базовый контракт грузим сразу — он без внешних зависимостей.
from ai.providers import AIProvider, ProviderError
from config import Settings

log = logging.getLogger(__name__)

# Канонический порядок fallback: OpenRouter → Groq → Ollama → Gemini.
_ORDER = ("openrouter", "groq", "ollama", "gemini")

# Провайдер → (модуль, класс). Импорт модуля ленивый (см. _instantiate).
_PROVIDER_MODULES: dict[str, tuple[str, str]] = {
    "openrouter": ("ai.providers.openrouter", "OpenRouterProvider"),
    "groq": ("ai.providers.groq", "GroqProvider"),
    "ollama": ("ai.providers.ollama", "OllamaProvider"),
    "gemini": ("ai.providers.gemini", "GeminiProvider"),
}


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


def _provider_order(settings: Settings) -> list[str]:
    """Порядок провайдеров: выбранный основной первым, затем канонический fallback."""
    primary = (settings.ai_provider or "openrouter").strip().lower()
    order: list[str] = []
    if primary in _PROVIDER_MODULES:
        order.append(primary)
    for name in _ORDER:
        if name not in order:
            order.append(name)
    return order


def _instantiate(name: str, settings: Settings) -> AIProvider:
    """Лениво импортирует модуль провайдера и создаёт его экземпляр.

    Импорт именно здесь: пока провайдер не понадобился в цепочке, его зависимости
    (например, google-genai для Gemini) не требуются. ``ImportError`` пробрасывается
    наверх — :func:`_build_providers` решает пропустить такой провайдер.
    """
    module_path, class_name = _PROVIDER_MODULES[name]
    module = importlib.import_module(module_path)
    provider_cls = getattr(module, class_name)

    if name == "openrouter":
        return provider_cls(settings.openrouter_api_key, settings.openrouter_model)
    if name == "groq":
        return provider_cls(settings.groq_api_key, settings.groq_model)
    if name == "ollama":
        return provider_cls(
            settings.ollama_host, settings.ollama_model, enabled=settings.ollama_enabled
        )
    if name == "gemini":
        return provider_cls(settings.gemini_api_key, settings.gemini_model)
    raise KeyError(name)  # неизвестный провайдер — не должно случаться


def _build_providers(settings: Settings) -> list[AIProvider]:
    """Строит цепочку провайдеров, пропуская тех, чьи зависимости не установлены."""
    providers: list[AIProvider] = []
    for name in _provider_order(settings):
        try:
            providers.append(_instantiate(name, settings))
        except ImportError as exc:
            # Пакет провайдера не установлен (напр. нет google-genai для Gemini).
            # Не роняем запуск — просто пропускаем этот провайдер.
            log.warning(
                "AI-провайдер '%s' пропущен: не установлена зависимость (%s). "
                "Он не нужен, если вы им не пользуетесь.",
                name, exc,
            )
        except Exception as exc:  # noqa: BLE001 — кривой конфиг провайдера не должен ронять запуск
            log.warning("AI-провайдер '%s' пропущен: %s", name, exc)
    return providers


def create_llm(settings: Settings) -> LLMRouter:
    """Фабрика роутера LLM: строит цепочку провайдеров и логирует диагностику."""
    router = LLMRouter(_build_providers(settings))
    available = [p.name for p in router._providers]
    configured = router.configured_names()
    log.info(
        "LLM роутер: доступны=[%s], настроены=[%s]",
        ", ".join(available) or "НЕТ",
        ", ".join(configured) or "НЕТ — задай ключ в .env",
    )
    if not configured:
        log.error(
            "AI ERROR: ни один провайдер не настроен. Впиши хотя бы один ключ в .env "
            "(OPENROUTER_API_KEY / GROQ_API_KEY / GEMINI_API_KEY) или включи Ollama. "
            "Проверка: python check_ai.py"
        )
    return router

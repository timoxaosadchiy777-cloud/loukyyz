"""Абстрактный слой LLM.

Вся логика вокруг ИИ (генерация откликов, скоринг лидов) обращается к провайдеру
только через интерфейс :class:`LLMClient`. Конкретная реализация
(:class:`GeminiLLM`) инкапсулирует SDK Google Gemini: выбор модели с резервной
(fallback), ретраи, graceful failure и JSON-режим. Чтобы позже сменить модель или
провайдера (OpenAI, Anthropic, локальная модель), достаточно написать новый класс
с тем же интерфейсом и вернуть его из :func:`create_llm` — остальной код не
меняется.

Провайдер намеренно «мягкий»: при отсутствии ключа или любой ошибке метод
``complete`` возвращает ``None``, а не бросает исключение, — пайплайн продолжает
работу и деградирует контролируемо.
"""

from __future__ import annotations

import logging
from typing import Protocol, runtime_checkable

from google import genai
from google.genai import errors as genai_errors
from google.genai import types

from config import Settings
from core.retry import retry_async

log = logging.getLogger(__name__)

# Дефолты, если модели не заданы/пусты в окружении. Совпадают с config.py.
_DEFAULT_MODEL = "gemini-2.0-flash"
_DEFAULT_FALLBACK = "gemini-2.5-flash"


@runtime_checkable
class LLMClient(Protocol):
    """Контракт провайдера LLM. Реализации не должны бросать наружу — только ``None``."""

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
        """Возвращает текст ответа модели или ``None`` при ошибке/отсутствии ключа.

        Args:
            system: Системная инструкция (роль/правила).
            user: Пользовательский запрос (контент).
            max_output_tokens: Ограничение длины ответа.
            temperature: «Разнообразие» ответа (0.0 — детерминированно).
            json_mode: Просить модель вернуть строго JSON (если провайдер умеет).
            label: Метка для логов/ретраев.
        """
        ...

    async def aclose(self) -> None:
        """Освобождает ресурсы клиента (если есть)."""
        ...


def _is_retryable(exc: BaseException) -> bool:
    """Ретраим 429 (rate limit) и 5xx/сеть; постоянные 4xx (400/403/404) — нет.

    404/400 внутри одной модели не ретраятся, но выше по стеку триггерят переход
    на резервную модель (:meth:`GeminiLLM.complete`).
    """
    if isinstance(exc, genai_errors.ClientError):
        return getattr(exc, "code", None) == 429
    return True  # ServerError (5xx) и прочие сетевые сбои


class GeminiLLM:
    """Реализация :class:`LLMClient` поверх Google Gemini (google-genai SDK).

    Пробует основную модель, а при её недоступности (404 «model not found»),
    исчерпанной квоте (429) или пустом/отфильтрованном ответе — резервную.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        primary = settings.gemini_model or _DEFAULT_MODEL
        fallback = settings.gemini_fallback_model or _DEFAULT_FALLBACK
        # Порядок моделей без дублей: [основная, резервная].
        self._models = [primary]
        if fallback and fallback != primary:
            self._models.append(fallback)
        # Клиент создаём только при наличии ключа; иначе complete() тихо отдаёт None.
        self._client = (
            genai.Client(api_key=settings.gemini_api_key)
            if settings.gemini_ready
            else None
        )
        if self._client is not None:
            log.info("LLM: Gemini, модели %s", " → ".join(self._models))

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
        if self._client is None:
            log.warning("GEMINI_API_KEY не задан — LLM недоступен (%s)", label)
            return None

        config = types.GenerateContentConfig(
            system_instruction=system,
            max_output_tokens=max_output_tokens,
            temperature=temperature,
            response_mime_type="application/json" if json_mode else None,
        )

        for model in self._models:
            text = await self._try_model(model, user, config, label)
            if text is not None:
                if model != self._models[0]:
                    log.info("LLM: ответ получен резервной моделью %s (%s)", model, label)
                return text
        log.error("LLM: все модели недоступны (%s): %s", label, ", ".join(self._models))
        return None

    async def _try_model(self, model, user, config, label) -> str | None:
        """Один вызов модели с ретраями; ``None`` — эту модель нужно пропустить."""
        try:
            response = await retry_async(
                lambda: self._client.aio.models.generate_content(
                    model=model,
                    contents=user,
                    config=config,
                ),
                attempts=self._settings.retry_attempts,
                base_delay=self._settings.retry_base_delay,
                exceptions=(genai_errors.APIError,),
                retry_if=_is_retryable,
                label=f"{label}@{model}",
            )
        except genai_errors.APIError as exc:
            # 404 (модель снята), 429 (квота), неверный ключ и т.п. — пробуем
            # следующую модель. Логируем причину.
            log.warning("Gemini модель %s недоступна (%s): %s", model, label, exc)
            return None
        except Exception as exc:  # noqa: BLE001 — любой иной сбой не должен ронять пайплайн
            log.error("Непредвиденная ошибка Gemini (%s, %s): %s", model, label, exc)
            return None

        if not response.candidates:
            log.warning("Gemini модель %s: пустой ответ (%s) — пробую следующую", model, label)
            return None
        try:
            text = (response.text or "").strip()
        except Exception:  # .text может бросать, если ответ заблокирован фильтром
            log.warning("Gemini модель %s: ответ отфильтрован (%s)", model, label)
            return None
        return text or None

    async def aclose(self) -> None:
        # У google-genai нет обязательного закрытия клиента — метод для симметрии API.
        return None


def create_llm(settings: Settings) -> LLMClient:
    """Фабрика провайдера LLM.

    Единственная точка, где выбирается конкретная реализация. Сменить модель или
    провайдера = поменять только это тело (или ветвление по настройке), не трогая
    ни скоринг, ни генерацию откликов.
    """
    return GeminiLLM(settings)

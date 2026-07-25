"""Абстрактный слой LLM.

Вся логика вокруг ИИ (генерация откликов, скоринг лидов) обращается к провайдеру
только через интерфейс :class:`LLMClient`. Конкретная реализация
(:class:`GeminiLLM`) инкапсулирует SDK Google Gemini: ретраи, graceful failure и
JSON-режим. Чтобы позже сменить модель или провайдера (OpenAI, Anthropic,
локальная модель), достаточно написать новый класс с тем же интерфейсом и
вернуть его из :func:`create_llm` — остальной код не меняется.

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

# Дефолт, если GEMINI_MODEL не задана/пуста. Совпадает с дефолтом в config.py.
_DEFAULT_MODEL = "gemini-1.5-flash"


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
    """Ретраим 429 (rate limit) и 5xx/сеть; постоянные 4xx (400/403/…) — нет."""
    if isinstance(exc, genai_errors.ClientError):
        return getattr(exc, "code", None) == 429
    return True  # ServerError (5xx) и прочие сетевые сбои


class GeminiLLM:
    """Реализация :class:`LLMClient` поверх Google Gemini (google-genai SDK)."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        # Модель берём из окружения (GEMINI_MODEL); если пусто — дефолт.
        self._model = settings.gemini_model or _DEFAULT_MODEL
        # Клиент создаём только при наличии ключа; иначе complete() тихо отдаёт None.
        self._client = (
            genai.Client(api_key=settings.gemini_api_key)
            if settings.gemini_ready
            else None
        )
        if self._client is not None:
            log.info("LLM: Gemini, модель %s", self._model)

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

        try:
            response = await retry_async(
                lambda: self._client.aio.models.generate_content(
                    model=self._model,
                    contents=user,
                    config=config,
                ),
                attempts=self._settings.retry_attempts,
                base_delay=self._settings.retry_base_delay,
                exceptions=(genai_errors.APIError,),
                retry_if=_is_retryable,
                label=label,
            )
        except genai_errors.APIError as exc:
            # Исчерпан лимит/квота (429 limit:0), недоступная модель, неверный ключ —
            # логируем и отдаём None: вызывающий код деградирует контролируемо.
            log.error("Ошибка Gemini API (%s, модель %s): %s", label, self._model, exc)
            return None
        except Exception as exc:  # noqa: BLE001 — любой иной сбой не должен ронять пайплайн
            log.error("Непредвиденная ошибка Gemini (%s): %s", label, exc)
            return None

        if not response.candidates:
            log.warning("Gemini не вернул ответ (%s): фильтр/пустой", label)
            return None

        try:
            text = (response.text or "").strip()
        except Exception:  # .text может бросать, если ответ заблокирован фильтром
            log.warning("Gemini: ответ отфильтрован (%s)", label)
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

"""Абстрактный слой LLM.

Вся логика вокруг ИИ (генерация откликов, скоринг лидов) обращается к провайдеру
только через интерфейс :class:`LLMClient`. Конкретная реализация
(:class:`GeminiLLM`) инкапсулирует SDK Google Gemini: выбор модели с резервной
(fallback), ретраи, диагностику и graceful failure. Чтобы позже сменить модель
или провайдера, достаточно написать новый класс с тем же интерфейсом и вернуть
его из :func:`create_llm` — остальной код не меняется.

Важно про диагностику: при ошибке провайдер НЕ проглатывает причину молча — он
пишет в лог «GEMINI ERROR: …» с кодом, статусом, сообщением и трейсбеком, а
наружу отдаёт ``None`` (чтобы пайплайн деградировал контролируемо, но было видно,
ЧТО именно сломалось).
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

_SDK_VERSION = getattr(genai, "__version__", "unknown")


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
        """Возвращает текст ответа модели или ``None`` при ошибке/отсутствии ключа."""
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


def _describe(exc: genai_errors.APIError) -> str:
    """Короткое человекочитаемое описание ошибки Gemini API."""
    code = getattr(exc, "code", "?")
    status = getattr(exc, "status", "?")
    message = getattr(exc, "message", None) or str(exc)
    return f"code={code} status={status} message={message}"


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
        self._log_startup_diagnostics()

    def _log_startup_diagnostics(self) -> None:
        """Стартовая диагностика LLM — без вывода самого ключа."""
        key_state = "найден" if self._settings.gemini_ready else "НЕ НАЙДЕН"
        log.info(
            "LLM диагностика: SDK=google-genai %s | провайдер=Gemini | "
            "GEMINI_API_KEY=%s | модель=%s | fallback=%s",
            _SDK_VERSION,
            key_state,
            self._models[0],
            self._models[1] if len(self._models) > 1 else "нет",
        )
        if self._client is None:
            log.error(
                "GEMINI ERROR: GEMINI_API_KEY не задан — скоринг и отклики работать "
                "НЕ будут. Впиши ключ в .env (GEMINI_API_KEY=…), получить: "
                "https://aistudio.google.com → Get API key"
            )

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
            log.error("GEMINI ERROR (%s): клиент не инициализирован (нет GEMINI_API_KEY)", label)
            return None

        # response_mime_type задаём только в JSON-режиме — не навязываем None.
        config_kwargs = dict(
            system_instruction=system,
            max_output_tokens=max_output_tokens,
            temperature=temperature,
        )
        if json_mode:
            config_kwargs["response_mime_type"] = "application/json"
        config = types.GenerateContentConfig(**config_kwargs)

        for model in self._models:
            text = await self._try_model(model, user, config, label)
            if text is not None:
                if model != self._models[0]:
                    log.info("LLM: ответ получен резервной моделью %s (%s)", model, label)
                return text
        log.error(
            "GEMINI ERROR (%s): все модели недоступны — %s. "
            "Проверь ключ/квоту/доступ к моделям (запусти: python check_ai.py)",
            label,
            ", ".join(self._models),
        )
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
            # 404 (модель снята), 429 (квота), 400/403 (ключ/доступ) — показываем
            # РЕАЛЬНУЮ причину и пробуем следующую модель.
            log.error("GEMINI ERROR (model=%s, %s): %s", model, label, _describe(exc))
            return None
        except Exception as exc:  # noqa: BLE001 — сеть/SDK/прочее не должно ронять пайплайн
            log.error(
                "GEMINI ERROR (model=%s, %s): %s: %s",
                model, label, type(exc).__name__, exc,
                exc_info=True,  # полный трейсбек в лог
            )
            return None

        if not response.candidates:
            reason = getattr(response, "prompt_feedback", None)
            log.warning(
                "GEMINI: модель %s вернула пустой ответ (%s)%s — пробую следующую",
                model, label, f" [{reason}]" if reason else "",
            )
            return None
        try:
            text = (response.text or "").strip()
        except Exception as exc:  # .text может бросать, если ответ заблокирован фильтром
            log.warning("GEMINI: ответ модели %s отфильтрован (%s): %s", model, label, exc)
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

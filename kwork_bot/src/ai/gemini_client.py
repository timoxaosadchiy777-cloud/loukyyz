"""Умный клиент Google Gemini.

Возможности:
- Fallback модели: primary (`gemini-1.5-flash`) → fallback (`gemini-2.5-flash`)
  при исчерпании квоты (429) или недоступности модели (404).
- Ретрай ТОЛЬКО временных ошибок (429 / 5xx / сеть/таймаут) с экспоненциальным
  бэкоффом; постоянные (400/401/403) — сразу без повторов.
- Обработка 429 через Retry-After / retryDelay из тела ошибки.
- Ограничение частоты запросов (RPS).
- Graceful failure: при любой неустранимой ошибке возвращает ``None`` — пайплайн
  не падает.
"""

from __future__ import annotations

import logging
import re

from google import genai
from google.genai import errors as genai_errors
from google.genai import types

from config.settings import Settings
from utils.ratelimiter import RateLimiter
from utils.retry import retry_async

log = logging.getLogger(__name__)

# Ищем предложенную задержку в теле 429 (Gemini кладёт retryDelay/"12s" в details).
_RETRY_DELAY_RE = re.compile(r'retry[_-]?delay["\s:]+"?(\d+(?:\.\d+)?)s?', re.IGNORECASE)
_RETRY_AFTER_RE = re.compile(r'retry-after["\s:]+"?(\d+(?:\.\d+)?)', re.IGNORECASE)


def _is_transient(exc: BaseException) -> bool:
    """Временные (ретраебельные) ошибки: 5xx, 429, сетевые/таймауты."""
    if isinstance(exc, genai_errors.ServerError):
        return True
    if isinstance(exc, genai_errors.ClientError):
        return getattr(exc, "code", None) == 429
    return isinstance(exc, (TimeoutError, ConnectionError))


def _retry_after_seconds(exc: BaseException) -> float | None:
    """Пытается извлечь рекомендованную задержку (сек) из тела ошибки 429."""
    text = str(exc)
    match = _RETRY_DELAY_RE.search(text) or _RETRY_AFTER_RE.search(text)
    return float(match.group(1)) if match else None


class GeminiClient:
    """Асинхронная обёртка над Google Gemini с fallback и устойчивостью."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._limiter = RateLimiter(settings.gemini_rps)
        # Список моделей по приоритету, без дублей.
        self._models: list[str] = [settings.gemini_model]
        if settings.gemini_fallback_model and settings.gemini_fallback_model not in self._models:
            self._models.append(settings.gemini_fallback_model)
        self._client: genai.Client | None = (
            genai.Client(api_key=settings.gemini_api_key) if settings.gemini_ready else None
        )
        if self._client is not None:
            log.info("GeminiClient: модели по приоритету — %s", ", ".join(self._models))

    async def generate(self, system_prompt: str, user_content: str) -> str | None:
        """Возвращает сгенерированный текст или ``None`` (без исключений наружу)."""
        if self._client is None:
            log.warning("GEMINI_API_KEY не задан — генерация пропущена")
            return None

        for model in self._models:
            try:
                text = await self._generate_once(model, system_prompt, user_content)
            except genai_errors.ClientError as exc:
                code = getattr(exc, "code", None)
                if code in (429, 404):
                    # Квота исчерпана / модель недоступна — пробуем следующую модель.
                    log.warning("Gemini %s недоступна (code=%s) — перехожу к fallback", model, code)
                    continue
                log.error("Gemini %s: постоянная ошибка (code=%s): %s", model, code, exc)
                return None
            except genai_errors.ServerError as exc:
                log.warning("Gemini %s: серверная ошибка после ретраев: %s — fallback", model, exc)
                continue
            except genai_errors.APIError as exc:
                log.error("Gemini %s: ошибка API: %s", model, exc)
                return None
            except Exception as exc:  # noqa: BLE001 — сеть/прочее не должно ронять пайплайн
                log.error("Gemini %s: непредвиденная ошибка: %s", model, exc)
                return None

            if text:
                return text
            log.warning("Gemini %s вернул пустой/отфильтрованный ответ", model)
            return None

        log.error("Gemini: все модели недоступны (%s)", ", ".join(self._models))
        return None

    async def _generate_once(self, model: str, system_prompt: str, user_content: str) -> str | None:
        config = types.GenerateContentConfig(
            system_instruction=system_prompt,
            max_output_tokens=self._settings.gemini_max_tokens,
            temperature=self._settings.gemini_temperature,
        )

        async def _call():
            await self._limiter.acquire()
            assert self._client is not None
            return await self._client.aio.models.generate_content(
                model=model,
                contents=user_content,
                config=config,
            )

        response = await retry_async(
            _call,
            attempts=self._settings.retry_attempts,
            base_delay=self._settings.retry_base_delay,
            max_delay=self._settings.retry_max_delay,
            exceptions=(Exception,),
            retry_if=_is_transient,
            delay_for=lambda exc, _attempt: _retry_after_seconds(exc),
            label=f"gemini:{model}",
        )

        if not getattr(response, "candidates", None):
            return None
        try:
            text = (response.text or "").strip()
        except Exception:  # noqa: BLE001 — .text бросает при блокировке контент-фильтром
            return None
        return text or None

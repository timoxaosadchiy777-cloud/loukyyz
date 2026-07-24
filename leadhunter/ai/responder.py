"""Генератор откликов на базе Google Gemini.

Пишет короткий, жёсткий и профессиональный отклик-решение под ТЗ клиента —
без приветствий, вводных слов и клише. Бесплатный ключ берётся в Google AI
Studio (https://aistudio.google.com).
"""

from __future__ import annotations

import logging

from google import genai
from google.genai import errors as genai_errors
from google.genai import types

from config import Settings
from core.models import Order
from core.retry import retry_async

log = logging.getLogger(__name__)

# Дефолт, если GEMINI_MODEL не задана/пуста. Совпадает с дефолтом в config.py.
_DEFAULT_MODEL = "gemini-1.5-flash"

SYSTEM_PROMPT = """\
Ты — senior-специалист, который откликается на фриланс-заказы. По тексту ТЗ \
напиши короткий, жёсткий и профессиональный отклик-решение.

Правила:
- Никаких приветствий и вводных слов («Здравствуйте», «Готов помочь», «Меня зовут»).
- Никаких клише и воды («имею большой опыт», «качественно и в срок», «обращайтесь»).
- Сразу по сути: покажи, что понял задачу, и предложи конкретное решение/подход.
- Укажи ключевой стек или шаги реализации, если это уместно.
- Один сильный уточняющий вопрос — только если без него нельзя оценить работу.
- Тон уверенный и компетентный, без лести и без самоуничижения.
- Объём: 3–6 предложений. Пиши на языке заказа (по умолчанию — русский).
- Верни только текст отклика, без пояснений и разметки.
"""


def _is_retryable(exc: BaseException) -> bool:
    """Ретраим 429 (rate limit) и 5xx; постоянные 4xx (400/403/…) — нет."""
    if isinstance(exc, genai_errors.ClientError):
        return getattr(exc, "code", None) == 429
    return True  # ServerError (5xx) и прочие сетевые сбои


class Responder:
    """Оборачивает Google Gemini для генерации откликов."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        # Модель берём из окружения (GEMINI_MODEL); если пусто — дефолт.
        # Аналог os.getenv("GEMINI_MODEL", _DEFAULT_MODEL), но через единый конфиг.
        self._model = settings.gemini_model or _DEFAULT_MODEL
        # Клиент создаём только при наличии ключа; иначе generate() тихо отдаёт None.
        self._client = (
            genai.Client(api_key=settings.gemini_api_key)
            if settings.gemini_ready
            else None
        )
        if self._client is not None:
            log.info("Gemini: используется модель %s", self._model)

    async def generate(self, order: Order) -> str | None:
        """Возвращает текст отклика или ``None`` при ошибке/отсутствии ключа.

        Временные сбои (429/5xx/сеть) ретраятся с экспоненциальной задержкой;
        постоянные (400/403/…) обрываются сразу.
        """
        if self._client is None:
            log.warning("GEMINI_API_KEY не задан — отклик не сгенерирован")
            return None

        user_content = (
            f"Заголовок заказа:\n{order.title}\n\n"
            f"Текст ТЗ:\n{order.description.strip()}"
        )
        config = types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            max_output_tokens=self._settings.gemini_max_tokens,
            temperature=self._settings.gemini_temperature,
        )

        try:
            response = await retry_async(
                lambda: self._client.aio.models.generate_content(
                    model=self._model,
                    contents=user_content,
                    config=config,
                ),
                attempts=self._settings.retry_attempts,
                base_delay=self._settings.retry_base_delay,
                exceptions=(genai_errors.APIError,),
                retry_if=_is_retryable,
                label=f"gemini:{order.dedup_key}",
            )
        except genai_errors.APIError as exc:
            # Исчерпан лимит/квота (429 limit:0), недоступная модель, неверный ключ
            # и т.п. — логируем и отдаём None: пайплайн продолжает работу.
            log.error("Ошибка Gemini API для %s (модель %s): %s", order.dedup_key, self._model, exc)
            return None
        except Exception as exc:  # noqa: BLE001 — любой иной сбой не должен ронять пайплайн
            log.error("Непредвиденная ошибка Gemini для %s: %s", order.dedup_key, exc)
            return None

        if not response.candidates:
            log.warning("Gemini не вернул ответ по заказу %s (фильтр/пустой)", order.dedup_key)
            return None

        try:
            text = (response.text or "").strip()
        except Exception:  # .text может бросать, если ответ заблокирован фильтром
            log.warning("Gemini: ответ по %s отфильтрован", order.dedup_key)
            return None
        return text or None

    async def aclose(self) -> None:
        # У google-genai нет обязательного закрытия клиента — метод для симметрии API.
        return None

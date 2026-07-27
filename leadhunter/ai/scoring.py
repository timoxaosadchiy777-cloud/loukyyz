"""AI Lead Scoring — оценка релевантности заказа по смыслу.

Заменяет фильтрацию по ключевым словам. По каждому новому заказу модель получает
профиль исполнителя (`profile.md`) и текст заказа и возвращает строгий JSON::

    {
      "score": 93,
      "category": "Telegram Bot",
      "reason": "...",
      "probability_of_sale": 70,
      "should_send": true
    }

Оценка — это семантическое суждение «насколько заказ подходит именно этому
исполнителю», а не совпадение слов. Никаких стоп-слов, whitelist/blacklist:
решение о релевантности принимает LLM по смыслу заказа, бюджету, типу клиента и
содержимому профиля.

При недоступности модели или неразборчивом ответе возвращается «неизвестно»
(:meth:`LeadScore.unknown`) — вызывающий код решает, что делать (LeadHunter не
теряет лид, а помечает его для ручной оценки).
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass

from ai.llm import LLMClient
from core.models import Order
from core.profile import ProfileLoader

log = logging.getLogger(__name__)

# Скоринг должен быть детерминированным и коротким.
_SCORING_TEMPERATURE = 0.0
_SCORING_MAX_TOKENS = 400

_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)

_SCORING_INSTRUCTIONS = """\
Ты — ассистент фрилансера, который оценивает входящие заказы с фриланс-площадок
и джоб-бордов.

Главный вопрос — НЕ «идеально ли вакансия совпадает с профилем», а
«СМОЖЕТ ЛИ исполнитель взять эту работу и заработать на ней». Это разные
вопросы, и второй заметно шире. Рассуждай как предприниматель, который ищет
оплачиваемую работу, а не как рекрутер, сверяющий резюме с требованиями.

Что учитывать:
- суть задачи: что реально нужно сделать (а не как называется должность);
- какую часть работы исполнитель закрывает своими навыками — прямо или через
  смежные области, перечисленные в профиле;
- бюджет и адекватность клиента;
- ясность ТЗ и шанс дойти до сделки.

СМЕЖНОСТЬ — ЭТО НОРМА. Заказ не обязан дословно повторять специализацию.
Если задача техническая и профильные навыки покрывают существенную её часть,
это подходящий лид, даже когда часть работы придётся изучить по ходу.

Верни СТРОГО один JSON-объект без пояснений, markdown и текста вокруг:
{
  "score": <целое 0..100 — коммерческая перспектива заказа для исполнителя>,
  "category": "<короткая категория, напр. 'Telegram Bot', 'Парсинг', 'Дизайн'>",
  "technology": "<стек через запятую, напр. 'python, aiogram, postgresql'; '' если не ясно>",
  "summary": "<1 предложение: суть заказа своими словами, по-русски>",
  "reason": "<1-2 предложения: почему такая оценка, по-русски>",
  "probability_of_sale": <целое 0..100 — вероятность довести заказ до сделки>,
  "should_send": <true|false — см. правило ниже>
}

Поля category, technology и summary — объективное описание САМОГО заказа, без
привязки к профилю: по ним система подбирает заказ разным исполнителям.

ШКАЛА score. Середина шкалы существует и используется ЧАЩЕ краёв —
большинство реальных заказов попадает в диапазон 30..80, а не в 0..10:

  90-100  прямое попадание в специализацию
          («нужен Telegram-бот», «парсер сайта на Python»)
  70-89   та же область, другой акцент
          (бэкенд-сервис, интеграция по API, автоматизация процесса)
  50-69   ЧАСТИЧНОЕ совпадение: задача техническая, профильные навыки
          закрывают существенную часть работы
          (AI/LLM-инженерия, SaaS-разработка, внутренние инструменты,
           MVP, технический продукт с автоматизацией)
  30-49   смежная область: техническая составляющая есть, но она не главная
          (product/project-роль вокруг технического продукта, аналитика с
           автоматизацией, QA с написанием скриптов)
  10-29   техническая часть минимальна, но не нулевая
  0-9     ОЧЕВИДНО нерелевантное: дизайн, графика, SEO, SMM, копирайтинг,
          поддержка клиентов, продажи — без всякой технической составляющей

ЧАСТАЯ ОШИБКА, которую нельзя повторять: занижать оценку из-за НАЗВАНИЯ
должности. «Product Manager», «Research Engineer», «Analyst», «Technical Lead»
сами по себе не повод ставить 2 или 5. Смотри, что внутри: если в задаче есть
AI, автоматизация, API, данные, бэкенд или разработка инструментов — это
минимум 40-60, даже если формально это «менеджерская» позиция.

probability_of_sale — шанс, что исполнитель реально получит ИМЕННО этот заказ
(конкуренция, бюджет, ясность ТЗ). Это НЕ то же самое, что score: заказ может
идеально подходить, но иметь низкий шанс из-за сотни откликов.

should_send — предохранитель от очевидного мусора, а НЕ второй фильтр качества.
Ставь false ТОЛЬКО когда заказ очевидно нерелевантен: ни одной технической
составляющей, либо это неоплачиваемая работа / «за долю в проекте».
Во всех остальных случаях — true, включая спорные и частично подходящие.
Порог по числу применит система отдельно; твоя задача — не отсеять лишнего.
Сомневаешься — ставь true.
"""


@dataclass(slots=True)
class LeadScore:
    """Результат скоринга заказа.

    Категория, технология и краткое описание — объективные признаки самого
    заказа: они не зависят от исполнителя, поэтому считаются ОДИН раз на лид и
    переиспользуются при подборе получателей (см. :mod:`core.fanout`).

    Attributes:
        score: Оценка соответствия 0..100, либо ``None`` — если ИИ недоступен.
        category: Категория заказа по мнению модели.
        reason: Короткое обоснование оценки.
        probability_of_sale: Вероятность довести заказ до сделки, 0..100 (или None).
        should_send: Рекомендация модели показывать ли заказ, либо ``None``.
        technology: Стек заказа через запятую (или пустая строка).
        summary: Суть заказа одним предложением (или пустая строка).
    """

    score: int | None
    category: str
    reason: str
    probability_of_sale: int | None
    should_send: bool | None
    technology: str = ""
    summary: str = ""

    @property
    def available(self) -> bool:
        """Есть ли валидная оценка от ИИ (иначе — решение нельзя принять по смыслу)."""
        return self.score is not None

    @classmethod
    def unknown(cls, reason: str = "ИИ недоступен — оцените вручную") -> LeadScore:
        return cls(
            score=None,
            category="",
            reason=reason,
            probability_of_sale=None,
            should_send=None,
        )


class ScoringService:
    """Оценивает заказы через LLM с учётом профиля исполнителя из `profile.md`."""

    def __init__(self, llm: LLMClient, profile: ProfileLoader) -> None:
        self._llm = llm
        self._profile = profile

    async def score(self, order: Order) -> LeadScore:
        """Возвращает :class:`LeadScore` для заказа (или ``unknown()`` при сбое)."""
        system = self._build_system_prompt()
        user = self._build_user_content(order)

        raw = await self._llm.complete(
            system=system,
            user=user,
            max_output_tokens=_SCORING_MAX_TOKENS,
            temperature=_SCORING_TEMPERATURE,
            json_mode=True,
            label=f"score:{order.dedup_key}",
        )
        if raw is None:
            return LeadScore.unknown()

        parsed = _parse_score(raw)
        if parsed is None:
            log.warning("Скоринг %s: не удалось разобрать ответ ИИ: %r", order.dedup_key, raw[:200])
            return LeadScore.unknown("не удалось разобрать ответ ИИ")
        return parsed

    def _build_system_prompt(self) -> str:
        profile = self._profile.read()
        if not profile:
            # Без профиля модель всё равно оценит по общему смыслу, но предупредим.
            log.debug("Скоринг без профиля (profile.md пуст/не найден)")
            return _SCORING_INSTRUCTIONS
        return f"{_SCORING_INSTRUCTIONS}\n\n## Профиль исполнителя\n\n{profile}"

    @staticmethod
    def _build_user_content(order: Order) -> str:
        budget = order.budget_raw or (
            f"${order.budget_value}" if order.budget_value is not None else "не указан"
        )
        return (
            f"Источник: {order.source}\n"
            f"Заголовок: {order.title}\n"
            f"Бюджет: {budget}\n\n"
            f"Описание заказа:\n{order.description.strip()}"
        )


# --- Разбор ответа модели ---

def _parse_score(text: str) -> LeadScore | None:
    """Извлекает JSON из ответа модели и превращает в :class:`LeadScore`."""
    match = _JSON_RE.search(text)
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None

    score = _as_pct(data.get("score"))
    if score is None:
        return None  # score обязателен

    category = str(data.get("category") or "").strip()[:80] or "—"
    reason = str(data.get("reason") or "").strip()

    # Вероятность сделки: если модель не вернула — берём score как приближение.
    probability = _as_pct(data.get("probability_of_sale"))
    if probability is None:
        probability = score

    should_send = _coerce_bool(data.get("should_send"))
    if should_send is None:
        # Модель не вернула флаг — используем оценку как запасной вывод.
        should_send = score >= 50

    return LeadScore(
        score=score,
        category=category,
        reason=reason,
        probability_of_sale=probability,
        should_send=should_send,
        technology=str(data.get("technology") or "").strip()[:120],
        summary=str(data.get("summary") or "").strip()[:300],
    )


def _as_pct(value: object) -> int | None:
    """Приводит значение к целому проценту 0..100 или ``None``."""
    try:
        result = int(round(float(value)))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return max(0, min(100, result))


def _coerce_bool(value: object) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        low = value.strip().lower()
        if low in {"true", "yes", "да", "1"}:
            return True
        if low in {"false", "no", "нет", "0"}:
            return False
    return None

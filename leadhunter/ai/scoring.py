"""AI Lead Scoring — оценка релевантности заказа по смыслу.

Заменяет фильтрацию по ключевым словам. По каждому новому заказу модель получает
профиль исполнителя (`profile.md`) и текст заказа и возвращает строгий JSON::

    {"score": 93, "category": "Telegram Bot", "reason": "...", "should_send": true}

Оценка — это семантическое суждение «насколько заказ подходит именно этому
исполнителю», а не совпадение слов. Никаких стоп-слов, whitelist/blacklist:
решение о релевантности принимает LLM по смыслу заказа и содержимому профиля.

При недоступности модели или неразборчивом ответе возвращается «неизвестно»
(:meth:`LeadScore.unknown`) — вызывающий код решает, что делать (LeadHunter не
теряет лид, а помечает его для ручной оценки).
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path

from ai.llm import LLMClient
from core.models import Order

log = logging.getLogger(__name__)

# Скоринг должен быть детерминированным и коротким.
_SCORING_TEMPERATURE = 0.0
_SCORING_MAX_TOKENS = 400

_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)

_SCORING_INSTRUCTIONS = """\
Ты — ассистент фрилансера, который оценивает входящие заказы с фриланс-площадок.
Твоя задача — понять СМЫСЛ заказа и решить, насколько он подходит исполнителю,
профиль которого дан ниже. Оценивай по смыслу, а не по совпадению слов.

Верни СТРОГО один JSON-объект без пояснений, markdown и текста вокруг:
{
  "score": <целое 0..100 — насколько заказ подходит исполнителю>,
  "category": "<короткая категория заказа, напр. 'Telegram Bot', 'Парсинг', 'Дизайн'>",
  "reason": "<1-2 предложения: почему такая оценка, по-русски>",
  "should_send": <true|false — стоит ли показывать заказ исполнителю>
}

Как выставлять score (ориентиры калибровки):
- «Нужен Telegram бот» → ~95
- «Автоматизация Excel / отчётности» → ~80
- «Парсер Avito / сбор данных» → ~90
- «Нарисовать логотип» → ~5
- «SEO-продвижение сайта» → ~3
Чем ближе суть заказа к специализации и желательным проектам из профиля — тем
выше. Чем ближе к нежелательным — тем ниже. Если заказ явно не по профилю,
ставь низкий score и should_send=false.

should_send — твоя рекомендация: true, если заказ стоит внимания исполнителя,
false — если это явно не его профиль. Порог по числу применит система отдельно,
твоя задача — честная оценка смысла.
"""


@dataclass(slots=True)
class LeadScore:
    """Результат скоринга заказа.

    Attributes:
        score: Оценка соответствия 0..100, либо ``None`` — если ИИ недоступен.
        category: Категория заказа по мнению модели.
        reason: Короткое обоснование оценки.
        should_send: Рекомендация модели показывать ли заказ, либо ``None``.
    """

    score: int | None
    category: str
    reason: str
    should_send: bool | None

    @property
    def available(self) -> bool:
        """Есть ли валидная оценка от ИИ (иначе — решение нельзя принять по смыслу)."""
        return self.score is not None

    @classmethod
    def unknown(cls, reason: str = "ИИ недоступен — оцените вручную") -> LeadScore:
        return cls(score=None, category="", reason=reason, should_send=None)


class ScoringService:
    """Оценивает заказы через LLM с учётом профиля исполнителя из `profile.md`."""

    def __init__(self, llm: LLMClient, *, profile_path: str | Path) -> None:
        self._llm = llm
        self._profile = _ProfileText(Path(profile_path))

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


class _ProfileText:
    """Ленивое чтение `profile.md` с горячей перезагрузкой по mtime."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._cache = ""
        self._mtime: float | None = None
        self._warned_missing = False

    def read(self) -> str:
        try:
            mtime = self._path.stat().st_mtime
        except OSError:
            if not self._warned_missing:
                log.warning("Файл профиля %s не найден — скоринг без профиля", self._path)
                self._warned_missing = True
            return self._cache

        if mtime != self._mtime:
            try:
                self._cache = self._path.read_text(encoding="utf-8").strip()
                self._mtime = mtime
                self._warned_missing = False
                log.info("Профиль загружен: %s (%s символов)", self._path, len(self._cache))
            except OSError as exc:
                log.warning("Не удалось прочитать профиль %s: %s", self._path, exc)
        return self._cache


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

    try:
        score = int(round(float(data.get("score"))))
    except (TypeError, ValueError):
        return None
    score = max(0, min(100, score))

    category = str(data.get("category") or "").strip()[:80] or "—"
    reason = str(data.get("reason") or "").strip()

    should_send = _coerce_bool(data.get("should_send"))
    if should_send is None:
        # Модель не вернула флаг — используем оценку как запасной вывод.
        should_send = score >= 50

    return LeadScore(score=score, category=category, reason=reason, should_send=should_send)


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

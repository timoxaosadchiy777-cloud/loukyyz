#!/usr/bin/env python3
"""Сравнение старого и нового scoring на одних и тех же лидах.

Запускать на машине, где работает ИИ (Ollama или ключ провайдера):

    python tools/compare_scoring.py

Скрипт прогоняет одни и те же заказы через СТАРЫЙ промпт (сохранён здесь как
исторический эталон) и через текущий, и печатает таблицу «до/после»: оценка,
should_send и итоговое решение при вашем ``min_score``.

Свои лиды можно подсунуть файлом: по одному JSON-объекту на строку с полями
title, description, budget_raw.

    python tools/compare_scoring.py my_leads.jsonl
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ai.llm import create_llm  # noqa: E402
from ai.scoring import _SCORING_INSTRUCTIONS, ScoringService, _parse_score  # noqa: E402
from config import get_settings  # noqa: E402
from core.decision import decide  # noqa: E402
from core.models import Order  # noqa: E402
from core.profile import ProfileLoader  # noqa: E402
from core.runtime_config import RuntimeConfig, RuntimeConfigStore  # noqa: E402

# Промпт до правки — нужен только для сравнения, в продукте не используется.
OLD_PROMPT = """\
Ты — ассистент фрилансера, который оценивает входящие заказы с фриланс-площадок.
Твоя задача — понять СМЫСЛ заказа и решить, насколько он подходит исполнителю,
профиль которого дан ниже. Оценивай по смыслу, а не по совпадению слов.

Верни СТРОГО один JSON-объект без пояснений, markdown и текста вокруг:
{
  "score": <целое 0..100 — насколько заказ подходит исполнителю>,
  "category": "<короткая категория>",
  "reason": "<1-2 предложения: почему такая оценка, по-русски>",
  "probability_of_sale": <целое 0..100>,
  "should_send": <true|false>
}

Как выставлять score (ориентиры калибровки):
- «Нужен Telegram бот» → ~95
- «Python automation» → ~90
- «Парсер / сбор данных» → ~90
- «Автоматизация Excel / отчётности» → ~80
- «Нарисовать логотип» → ~5
- «SEO-продвижение сайта» → ~3
Чем ближе суть заказа к специализации и желательным проектам из профиля — тем
выше. Чем ближе к нежелательным — тем ниже. Если заказ явно не по профилю,
ставь низкий score и should_send=false.

should_send — твоя рекомендация: true, если заказ стоит внимания исполнителя,
false — если это явно не его профиль. Порог по числу применит система отдельно.
"""

# Лиды из отчёта о проблеме плюс контрольные: заведомо профильный и заведомо
# мусорный — по ним видно, что новый промпт не «пропускает всё подряд».
SAMPLE_LEADS = [
    {
        "title": "AI Research Engineer",
        "description": (
            "Research and develop LLM-based systems. Build evaluation pipelines, "
            "fine-tune models, integrate model APIs into production services. "
            "Python, PyTorch, distributed training."
        ),
        "budget_raw": "",
    },
    {
        "title": "Product Manager / QA Analyst",
        "description": (
            "Own the product backlog for an internal automation platform. "
            "Write test scenarios, automate regression checks, work closely with "
            "backend engineers on API contracts."
        ),
        "budget_raw": "",
    },
    {
        "title": "Product Marketing Manager",
        "description": (
            "Drive go-to-market for a SaaS analytics product. Positioning, "
            "messaging, competitive research, launch campaigns."
        ),
        "budget_raw": "",
    },
    {
        "title": "Technical Product Manager (AI / Automation)",
        "description": (
            "Define and ship AI-powered internal tools. Prototype workflows, "
            "spec integrations with third-party APIs, work hands-on with data."
        ),
        "budget_raw": "",
    },
    {
        "title": "Нужен Telegram-бот для приёма заявок",
        "description": "Бот на Python: приём заявок, оплата, выгрузка в Google Sheets.",
        "budget_raw": "$500",
    },
    {
        "title": "Нарисовать логотип и фирменный стиль",
        "description": "Логотип, палитра, гайдлайн. Иллюстратор или Фигма.",
        "budget_raw": "$200",
    },
]


def _load_leads(path: str | None) -> list[dict]:
    if not path:
        return SAMPLE_LEADS
    leads = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if line.strip():
            leads.append(json.loads(line))
    return leads


async def _score_with(llm, profile: str, prompt: str, order: Order):
    """Оценивает заказ произвольным промптом (для сравнения версий)."""
    system = f"{prompt}\n\n## Профиль исполнителя\n\n{profile}" if profile else prompt
    raw = await llm.complete(
        system=system,
        user=ScoringService._build_user_content(order),
        max_output_tokens=400,
        temperature=0.0,
        json_mode=True,
        label="compare",
    )
    return _parse_score(raw) if raw else None


def _verdict(score, min_score: int) -> str:
    if score is None:
        return "ИИ не ответил"
    decision = decide(score, min_score=min_score)
    if decision is None:
        return "вручную"
    return "ДОСТАВЛЕН" if decision else "отклонён"


async def main() -> int:
    settings = get_settings()
    config = RuntimeConfigStore(settings.runtime_config_file, defaults=RuntimeConfig())
    min_score = config.current().min_score
    profile = ProfileLoader(settings.profile_file).read()

    llm = create_llm(settings, config.current().llm)
    leads = _load_leads(sys.argv[1] if len(sys.argv) > 1 else None)

    print(f"Провайдер: {config.current().llm.provider} · min_score={min_score}")
    print(f"Профиль:   {'загружен' if profile else 'ПУСТ — оценки будут случайными'}")
    print("=" * 100)
    print(f"{'Лид':<44} {'БЫЛО':>22} {'СТАЛО':>22}")
    print("-" * 100)

    improved = 0
    for lead in leads:
        order = Order(
            source="rss",
            external_id="cmp",
            title=lead["title"],
            url="https://example.com",
            description=lead.get("description", ""),
            budget_raw=lead.get("budget_raw", ""),
        )
        old = await _score_with(llm, profile, OLD_PROMPT, order)
        new = await _score_with(llm, profile, _SCORING_INSTRUCTIONS, order)

        def cell(s) -> str:
            if s is None:
                return "нет ответа"
            return f"{s.score:>3} {'✓' if s.should_send else '✗'} {_verdict(s, min_score)}"

        title = lead["title"][:43]
        print(f"{title:<44} {cell(old):>22} {cell(new):>22}")

        if old and new and new.score > old.score:
            improved += 1

    print("-" * 100)
    print(f"Оценка выросла у {improved} из {len(leads)} лидов")
    print("\nЛегенда: score · ✓/✗ should_send · итоговое решение при вашем min_score")

    await llm.aclose()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

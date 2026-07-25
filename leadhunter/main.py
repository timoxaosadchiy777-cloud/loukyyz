"""LeadHunter — точка входа.

Запускает асинхронно три компонента:
  1. RSS-парсер — свежие лиды с международных площадок (Upwork RSS, джоб-борды).
  2. Пайплайн обработки — AI Lead Scoring → решение → отклик → пуш карточки.
  3. Aiogram-бот — доставка карточек и CRM-управление.

Новый конвейер LeadHunter 2.0:

    Parser → AI Score → Decision → Response → Telegram → SQLite

Решение о релевантности принимает ИИ (по смыслу заказа и `profile.md`), а не
ключевые слова. Бюджет — единственный дешёвый предфильтр до обращения к LLM.

Запуск неинтерактивный: без ввода с консоли, без авторизации и ожидания кода.
"""

from __future__ import annotations

import asyncio
import logging

from ai.llm import create_llm
from ai.responder import Responder
from ai.scoring import ScoringService
from bot.alerts import Alerter
from bot.bot import create_bot, create_dispatcher, push_card
from config import Settings, get_settings
from core.decision import apply_score, decide
from core.filters import parse_budget
from core.logging import setup_logging
from core.models import CrmStatus, Order
from core.runtime_config import RuntimeConfig, RuntimeConfigStore
from database.db import Database
from parsers.rss_parser import RssParser

log = logging.getLogger("leadhunter")

_MANUAL_FALLBACK = (
    "(Не удалось сгенерировать отклик автоматически — сформулируй вручную по ТЗ.)"
)


async def handle_order(
    order: Order,
    *,
    db: Database,
    scorer: ScoringService,
    responder: Responder,
    bot,
    alerter: Alerter,
    settings: Settings,
    config: RuntimeConfigStore,
) -> None:
    """Обрабатывает один заказ по конвейеру Parser → AI Score → Decision → …"""
    cfg = config.current()

    # 0. Источник выключен в настройках — молча пропускаем (без запроса к ИИ).
    if not cfg.source_enabled(order.source):
        log.debug("Источник %s выключен — пропуск %s", order.source, order.dedup_key)
        return

    # Бюджет берём только из явно распознанной суммы (budget_raw), а не из всего
    # описания — иначе случайные числа в тексте вакансии дадут ложный фильтр.
    if order.budget_value is None and order.budget_raw:
        order.budget_value = parse_budget(order.budget_raw)

    # 1. Дедупликация по источнику + external_id.
    if await db.is_duplicate(order.source, order.external_id):
        log.debug("Дубликат пропущен: %s", order.dedup_key)
        return

    # 2. Дешёвый предфильтр по бюджету — ДО обращения к LLM (экономия запросов).
    #    Отсекаем только когда сумма распознана и она ниже порога.
    if order.budget_value is not None and order.budget_value < cfg.min_budget:
        log.info(
            "Отсеян по бюджету %s (%s < %s)",
            order.dedup_key,
            order.budget_value,
            cfg.min_budget,
        )
        await db.save_order(order, response="", status="filtered")
        return

    # 3. AI Lead Scoring — оценка релевантности по смыслу и profile.md.
    log.info("Новый заказ %s — оцениваю через ИИ", order.dedup_key)
    lead_score = await scorer.score(order)
    apply_score(order, lead_score)

    # 4. Decision — пускать ли заказ дальше.
    decision = decide(lead_score, min_score=cfg.min_score)
    if decision is False:
        log.info(
            "ИИ отклонил %s (score=%s, %s)",
            order.dedup_key,
            order.score,
            order.category or order.reason,
        )
        await db.save_order(order, response="", status="rejected")
        return
    if decision is None:
        # ИИ недоступен/не разобрал ответ. Не теряем лид и не откатываемся к
        # ключевым словам: доставляем карточку с пометкой «оцените вручную».
        log.warning("ИИ недоступен для %s — карточка уйдёт без оценки", order.dedup_key)
        await alerter.alert(
            "ИИ не смог оценить заказы — карточки уходят без AI Score. Проверь ключ/логи.",
            key="ai-scoring-failure",
        )

    # 5. Response — генерация отклика через LLM.
    response = await responder.generate(order)
    if not response:
        response = _MANUAL_FALLBACK
        await alerter.alert(
            "Gemini не смог сгенерировать отклик — карточки уходят без ИИ-текста. Проверь логи/ключ.",
            key="ai-response-failure",
        )

    # 6. SQLite — сохранение с оценкой и статусом воронки NEW.
    order_id = await db.save_order(
        order, response=response, status="new", crm_status=CrmStatus.NEW
    )
    if order_id is None:
        log.debug("Гонка дедупликации, карточка не отправлена: %s", order.dedup_key)
        return

    # 7. Telegram — доставка карточки владельцу.
    if settings.owner_id:
        await push_card(bot, settings.owner_id, order, response, order_id)
    else:
        log.warning("OWNER_ID не задан — карточка %s не отправлена", order.dedup_key)


async def process_orders(
    queue: "asyncio.Queue[Order]",
    *,
    db: Database,
    scorer: ScoringService,
    responder: Responder,
    bot,
    alerter: Alerter,
    settings: Settings,
    config: RuntimeConfigStore,
) -> None:
    """Бесконечный потребитель очереди заказов."""
    while True:
        order = await queue.get()
        try:
            await handle_order(
                order,
                db=db,
                scorer=scorer,
                responder=responder,
                bot=bot,
                alerter=alerter,
                settings=settings,
                config=config,
            )
        except Exception:
            log.exception("Ошибка обработки заказа %s", order.dedup_key)
        finally:
            queue.task_done()


async def main() -> None:
    settings = get_settings()
    setup_logging(settings.log_level)
    log.info("Запуск LeadHunter…")

    db = Database(settings.database_path)
    await db.connect()

    config = RuntimeConfigStore(
        settings.runtime_config_path, defaults=RuntimeConfig()
    )

    llm = create_llm(settings)
    scorer = ScoringService(llm, profile_path=settings.profile_path)
    responder = Responder(llm, settings)

    bot = create_bot(settings)
    dp = create_dispatcher(db, settings)
    alerter = Alerter(bot, settings.owner_id, settings.alert_cooldown)

    queue: "asyncio.Queue[Order]" = asyncio.Queue()
    rss = RssParser(queue, settings, alerter)

    tasks = [
        asyncio.create_task(dp.start_polling(bot), name="bot"),
        asyncio.create_task(rss.run_safe(), name="rss"),
        asyncio.create_task(
            process_orders(
                queue,
                db=db,
                scorer=scorer,
                responder=responder,
                bot=bot,
                alerter=alerter,
                settings=settings,
                config=config,
            ),
            name="processor",
        ),
    ]

    try:
        await asyncio.gather(*tasks)
    finally:
        log.info("Остановка LeadHunter…")
        for task in tasks:
            task.cancel()
        await responder.aclose()
        await db.close()
        await bot.session.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        pass

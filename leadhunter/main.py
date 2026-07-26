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

from ai.llm import LLMRouter, create_llm
from ai.responder import Responder
from ai.scoring import ScoringService
from bot.alerts import Alerter
from bot.bot import create_bot, create_dispatcher, push_card
from config import Settings, get_settings
from core.decision import apply_score, decide
from core.filters import parse_budget
from core.logging import setup_logging
from core.models import CrmStatus, Order
from core.profile import ProfileLoader
from core.runtime_config import RuntimeConfig, RuntimeConfigStore
from database.db import Database

# RssParser импортируется лениво в main(): он тянет feedparser, а держать
# пайплайн (handle_order) импортируемым без этой зависимости удобно для тестов.

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
    llm: LLMRouter,
    bot,
    alerter: Alerter,
    settings: Settings,
    config: RuntimeConfigStore,
) -> None:
    """Обрабатывает один заказ по конвейеру Parser → AI Score → Decision → …"""
    cfg = config.current()

    # 0. Источник выключен в настройках — пропускаем (без запроса к ИИ).
    if not cfg.source_enabled(order.source):
        log.info(
            "Пропуск %s: источник '%s' выключен (enabled_sources=%s)",
            order.dedup_key, order.source, list(cfg.enabled_sources) or "все",
        )
        return

    # Бюджет берём только из явно распознанной суммы (budget_raw), а не из всего
    # описания — иначе случайные числа в тексте вакансии дадут ложный фильтр.
    if order.budget_value is None and order.budget_raw:
        order.budget_value = parse_budget(order.budget_raw)

    # 1. Дедупликация по источнику + external_id.
    if await db.is_duplicate(order.source, order.external_id):
        log.info("Пропуск %s: уже в базе (обработан ранее)", order.dedup_key)
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

    # 3. AI Lead Scoring — оценка релевантности по смыслу, profile.md, бюджету.
    log.info("AI scoring lead %s", order.external_id)
    lead_score = await scorer.score(order)
    apply_score(order, lead_score)

    # 4. Decision — пускать ли заказ дальше.
    decision = decide(lead_score, min_score=cfg.min_score)
    decision_label = "send" if decision else ("reject" if decision is False else "manual")
    # Явные, читаемые логи скоринга (именно AI scoring, а не «генерирую отклик»).
    log.info("score=%s", "n/a" if order.score is None else order.score)
    log.info("category=%s", order.category or "n/a")
    log.info("probability_of_sale=%s", "n/a" if order.probability_of_sale is None else order.probability_of_sale)
    log.info("decision=%s", decision_label)

    if decision is False:
        log.info("ИИ отклонил %s: %s", order.dedup_key, order.reason or order.category)
        await db.save_order(order, response="", status="rejected")
        return
    manual_mode = decision is None
    if manual_mode:
        # ИИ недоступен/не разобрал ответ. Не теряем лид и не откатываемся к
        # ключевым словам: доставляем карточку, показывая РЕАЛЬНУЮ причину.
        reason = llm.last_error or "не удалось разобрать ответ ИИ"
        order.reason = f"AI недоступен — {reason}"
        log.warning("AI ERROR для %s: %s", order.dedup_key, reason)
        await alerter.alert(
            f"AI не смог оценить заказы. Причина: {reason}. Проверь: python check_ai.py",
            key="ai-scoring-failure",
        )

    # 5. Response — отклик генерируем ТОЛЬКО для прошедших порог лидов.
    #    Экономия: слабые лиды и ручной режим не тратят второй запрос к модели.
    if manual_mode:
        response = (
            f"{_MANUAL_FALLBACK}\nПричина: {llm.last_error or 'AI недоступен'}"
        )
        log.info("Отклик не генерируется (ручной режим): %s", order.dedup_key)
    else:
        response = await responder.generate(order, analysis=lead_score)
        if not response:
            reason = llm.last_error or "неизвестная ошибка"
            response = f"{_MANUAL_FALLBACK}\nПричина: {reason}"
            await alerter.alert(
                f"AI не сгенерировал отклик. Причина: {reason}. Проверь: python check_ai.py",
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
    llm: LLMRouter,
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
                llm=llm,
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
    log.info("Запуск LeadHunter 2.0…")

    # Пути резолвим от каталога проекта — работает из любого рабочего каталога.
    profile_file = settings.profile_file
    runtime_file = settings.runtime_config_file
    db_file = settings.database_file
    log.info("Профиль:   %s (%s)", profile_file, "найден" if profile_file.exists() else "НЕ найден")
    log.info("Настройки: %s", runtime_file)
    log.info("База:      %s", db_file)

    db = Database(str(db_file))
    await db.connect()

    config = RuntimeConfigStore(runtime_file, defaults=RuntimeConfig())

    profile = ProfileLoader(profile_file)
    # Провайдер LLM берём из settings.yaml (блок llm:) — по умолчанию локальный Ollama.
    llm = create_llm(settings, config.current().llm)
    scorer = ScoringService(llm, profile)
    responder = Responder(llm, settings, profile)

    bot = create_bot(settings)
    dp = create_dispatcher(db, settings)
    alerter = Alerter(bot, settings.owner_id, settings.alert_cooldown)

    # Ленивый импорт: feedparser нужен только для реального запуска парсера,
    # поэтому держим его здесь — модуль main остаётся импортируемым без feedparser.
    from parsers.rss_parser import RssParser

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
                llm=llm,
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

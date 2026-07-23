"""LeadHunter — точка входа.

Запускает асинхронно четыре компонента:
  1. Telegram-парсер (Telethon) — мониторинг чатов.
  2. Kwork-парсер (Playwright) — свежие заказы с биржи.
  3. Пайплайн обработки — дедуп → фильтр → генерация отклика → пуш карточки.
  4. Aiogram-бот — доставка карточек и инлайн-управление.
"""

from __future__ import annotations

import asyncio
import logging

from ai.responder import Responder
from bot.alerts import Alerter
from bot.bot import create_bot, create_dispatcher, push_card
from config import Settings, get_settings
from core.filters import is_junk, parse_budget
from core.logging import setup_logging
from core.models import Order
from database.db import Database
from parsers.kwork_parser import KworkParser
from parsers.telegram_parser import TelegramParser

log = logging.getLogger("leadhunter")


async def handle_order(
    order: Order,
    *,
    db: Database,
    responder: Responder,
    bot,
    alerter: Alerter,
    settings: Settings,
) -> None:
    """Обрабатывает один заказ по всей цепочке."""
    if order.budget_value is None:
        order.budget_value = parse_budget(order.budget_raw or order.description)

    # 1. Дедупликация по источнику + external_id.
    if await db.is_duplicate(order.source, order.external_id):
        log.debug("Дубликат пропущен: %s", order.dedup_key)
        return

    # 2. Фильтрация мусора (низкий бюджет / стоп-фразы).
    junk, reason = is_junk(
        order,
        min_budget=settings.min_budget,
        junk_phrases=settings.junk_phrases,
    )
    if junk:
        log.info("Отфильтрован %s (%s)", order.dedup_key, reason)
        await db.save_order(order, response="", status="filtered")
        return

    # 3. Генерация отклика через Claude.
    log.info("Новый заказ %s — генерирую отклик", order.dedup_key)
    response = await responder.generate(order)
    if not response:
        response = "(Не удалось сгенерировать отклик автоматически — сформулируй вручную по ТЗ.)"
        # Систематические сбои ИИ подсвечиваем владельцу (с троттлингом).
        await alerter.alert(
            "Claude не смог сгенерировать отклик — карточки уходят без ИИ-текста. Проверь логи/ключ.",
            key="ai-failure",
        )

    # 4. Сохранение и доставка карточки владельцу.
    order_id = await db.save_order(order, response=response, status="new")
    if order_id is None:
        log.debug("Гонка дедупликации, карточка не отправлена: %s", order.dedup_key)
        return

    if settings.owner_id:
        await push_card(bot, settings.owner_id, order, response, order_id)
    else:
        log.warning("OWNER_ID не задан — карточка %s не отправлена", order.dedup_key)


async def process_orders(
    queue: "asyncio.Queue[Order]",
    *,
    db: Database,
    responder: Responder,
    bot,
    alerter: Alerter,
    settings: Settings,
) -> None:
    """Бесконечный потребитель очереди заказов."""
    while True:
        order = await queue.get()
        try:
            await handle_order(
                order,
                db=db,
                responder=responder,
                bot=bot,
                alerter=alerter,
                settings=settings,
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

    responder = Responder(settings)
    bot = create_bot(settings)
    dp = create_dispatcher(db, settings)
    alerter = Alerter(bot, settings.owner_id, settings.alert_cooldown)

    queue: "asyncio.Queue[Order]" = asyncio.Queue()
    telegram = TelegramParser(queue, settings, alerter)
    kwork = KworkParser(queue, settings, alerter)

    tasks = [
        asyncio.create_task(dp.start_polling(bot), name="bot"),
        asyncio.create_task(telegram.run_safe(), name="telegram"),
        asyncio.create_task(kwork.run_safe(), name="kwork"),
        asyncio.create_task(
            process_orders(
                queue,
                db=db,
                responder=responder,
                bot=bot,
                alerter=alerter,
                settings=settings,
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

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
import signal

from ai.llm import LLMRouter, create_llm
from ai.responder import Responder
from ai.scoring import ScoringService
from bot.alerts import Alerter
from bot.bot import create_bot, create_dispatcher, push_card, setup_commands
from config import Settings, get_settings
from core.decision import apply_score, decide
from core.fanout import Recipient, prefilter, select
from core.filters import parse_budget
from core.freshness import age_hours, is_fresh
from core.health import Heartbeat
from core.logging import setup_logging
from core.models import CrmStatus, Order
from core.profile import ProfileLoader
from core.ratelimit import AsyncThrottle
from core.runtime_config import RuntimeConfig, RuntimeConfigStore
from database.db import Database

# RssParser импортируется лениво в main(): он тянет feedparser, а держать
# пайплайн (handle_order) импортируемым без этой зависимости удобно для тестов.

log = logging.getLogger("leadhunter")

_MANUAL_FALLBACK = (
    "(Не удалось сгенерировать отклик автоматически — сформулируй вручную по ТЗ.)"
)

# Ограничение рассылки: Telegram допускает ~30 сообщений в секунду на бота и
# за превышение временно банит отправку. Лимит общий на процесс, поэтому и
# ограничитель общий: паузы внутри одной рассылки недостаточно — при десятке
# получателей на лид она не срабатывает, а подряд идущие лиды складываются.
_send_throttle = AsyncThrottle(rate_per_second=20)


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

    # 0.5. Отсечка устаревших лидов. Парсеры фильтруют сами, но RSS и любой
    #      будущий источник могут отдать старьё — проверяем ещё раз здесь.
    if not is_fresh(order, max_age_hours=settings.max_lead_age_hours):
        hours = age_hours(order)
        log.info(
            "Пропуск %s: опубликован %.0f ч назад (лимит %s ч)",
            order.dedup_key, hours or 0, settings.max_lead_age_hours,
        )
        return

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

    # 3. Получатели: владелец + все пользователи с доступом, каждый со своими
    #    фильтрами. У владельца фильтров обычно нет — дефолтные пропускают всё,
    #    поэтому он получает лиды ровно как до fan-out.
    recipients = await load_recipients(db, settings.owner_id)
    if not recipients:
        log.warning("Некому отправлять %s: нет ни владельца, ни пользователей", order.dedup_key)
        await db.save_order(order, response="", status="filtered")
        return

    # 4. Стадия 1 — дешёвый отбор БЕЗ ИИ: биржа, бюджет, слова в тексте лида.
    #    Если лид не нужен никому, он не стоит нам ни одного запроса к модели.
    candidates = prefilter(recipients, order)
    if not candidates:
        log.info(
            "Пропуск %s: не подходит никому из %s получателей (ИИ не вызывался)",
            order.dedup_key,
            len(recipients),
        )
        await db.save_order(order, response="", status="filtered")
        return

    # 5. AI Lead Scoring — ОДИН запрос на лид, независимо от числа получателей.
    #    Категория/стек/суть объективны, поэтому переиспользуются для всех.
    log.info("AI scoring lead %s (кандидатов: %s)", order.external_id, len(candidates))
    lead_score = await scorer.score(order)
    apply_score(order, lead_score)

    # 6. Decision — пускать ли заказ дальше (глобальный порог качества).
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

    # 7. Стадия 2 — добираем то, что стало известно от ИИ: категорию и стек.
    if manual_mode:
        # ИИ не ответил: категорию сверять нечем, поэтому доверяем стадии 1.
        matched = candidates
    else:
        matched = select(candidates, order)
    if not matched:
        log.info(
            "Отсеян по персональным фильтрам %s (категория '%s' никому не подошла)",
            order.dedup_key,
            order.category,
        )
        await db.save_order(order, response="", status="filtered")
        return

    # 8. Response — ОДИН отклик на лид, и только когда есть кому его отправить.
    #    Профиль исполнителя (profile.md) общий, поэтому отдельный запрос на
    #    каждого получателя дал бы одинаковый текст и лишние вызовы API.
    #    Каждому кладём свою копию — её можно переписать, не задев остальных.
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

    # 9. SQLite — сохранение с оценкой и статусом воронки NEW.
    order_id = await db.save_order(
        order, response=response, status="new", crm_status=CrmStatus.NEW
    )
    if order_id is None:
        log.debug("Гонка дедупликации, карточка не отправлена: %s", order.dedup_key)
        return

    # 10. Telegram — карточка каждому подошедшему получателю.
    delivered = await deliver(bot, db, matched, order, response, order_id)
    log.info("Доставлено %s из %s получателей: %s", delivered, len(matched), order.dedup_key)


async def load_recipients(db: Database, owner_id: int) -> list[Recipient]:
    """Владелец плюс все пользователи с доступом, каждый со своими фильтрами.

    Один запрос на лид, а не 1+N: выборка с JOIN живёт в Database.
    """
    return [
        Recipient(telegram_id, settings)
        for telegram_id, settings in await db.list_recipients(owner_id)
    ]


async def deliver(
    bot,
    db: Database,
    recipients: list[Recipient],
    order: Order,
    response: str,
    order_id: int,
) -> int:
    """Рассылает карточку получателям. Возвращает число доставленных.

    Доставку помечаем ДО отправки: строка в ``lead_deliveries`` резервирует
    лид за пользователем, поэтому повторно он его не получит. Ошибка отправки
    (пользователь заблокировал бота) не должна ронять рассылку остальным.
    """
    delivered = 0
    for recipient in recipients:
        if not await db.mark_delivered(recipient.telegram_id, order_id, response):
            log.debug(
                "Пропуск доставки %s: пользователь %s уже получал этот лид",
                order.dedup_key,
                recipient.telegram_id,
            )
            continue
        await _send_throttle.wait()
        try:
            await push_card(bot, recipient.telegram_id, order, response, order_id)
            delivered += 1
        except Exception:
            log.exception(
                "Не удалось отправить карточку %s пользователю %s",
                order.dedup_key,
                recipient.telegram_id,
            )
    return delivered


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
    setup_logging(
        settings.log_level,
        log_file=settings.log_path,
        max_bytes=settings.log_max_bytes,
        backups=settings.log_backups,
    )
    log.info("Запуск LeadHunter…")

    problems = check_configuration(settings)
    if problems:
        # Падать трейсбеком на пустом BOT_TOKEN — плохой первый опыт покупателя.
        # Говорим человеческим языком, что именно поправить в .env.
        log.error("Бот не может стартовать:")
        for problem in problems:
            log.error("  • %s", problem)
        return

    # Пути резолвим от каталога проекта — работает из любого рабочего каталога.
    profile_file = settings.profile_file
    runtime_file = settings.runtime_config_file
    db_file = settings.database_file
    # ID администратора печатаем явно: если он вписан с ошибкой, /admin просто
    # молчит (так и задумано — бот не подсказывает наличие админки посторонним),
    # и без этой строки владелец не поймёт, почему у него нет доступа.
    log.info(
        "Администратор: OWNER_ID=%s%s",
        settings.owner_id or "не задан",
        " · DEV_MODE включён — доступ открыт ВСЕМ" if settings.dev_mode else "",
    )
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
    alerter = Alerter(bot, settings.owner_id, settings.alert_cooldown)

    # Парсеры собираются по реестру источников: подключить биржу = строка в
    # core/sources.py. Импорт ленивый, поэтому отсутствие зависимости одного
    # источника не мешает остальным (см. parsers/registry.py).
    #
    # Состав опрашиваемых бирж задают САМИ пользователи в боте: супервизор
    # держит парсер, пока биржу выбрал хотя бы один человек, и гасит его, когда
    # не выбрал никто. Один парсер на биржу на всех — по-другому нельзя: полсотни
    # клиентов означали бы полсотни одинаковых запросов к сайту и быстрый бан.
    from parsers.supervisor import SourceSupervisor

    queue: "asyncio.Queue[Order]" = asyncio.Queue(maxsize=settings.queue_maxsize)
    supervisor = SourceSupervisor(queue, settings, db, alerter, config=config)
    # Стартуем то, что уже выбрано, до первого фонового прохода — иначе первую
    # минуту после запуска бот не опрашивал бы ничего.
    await supervisor.reconcile()
    log.info("Опрашиваются биржи: %s", ", ".join(sorted(supervisor.active)) or "ни одной")
    if supervisor.blocked:
        # Самая обидная тишина — когда биржа включена в боте, а её глушит
        # забытый список в settings.yaml. Говорим об этом прямо при старте.
        log.warning(
            "Биржи %s включены пользователями, но запрещены enabled_sources в %s. "
            "Уберите список (enabled_sources: []), если это не задумано",
            ", ".join(sorted(supervisor.blocked)), runtime_file,
        )

    dp = create_dispatcher(db, settings, responder, supervisor)
    # Подсказки команд в синей кнопке Telegram (владельцу — ещё и админские).
    await setup_commands(bot, settings.owner_id)

    heartbeat = Heartbeat(settings.health_path, settings.health_interval)

    # Критические задачи: их завершение означает, что работать дальше нельзя.
    # Парсеры сюда НЕ входят — они перезапускаются сами (BaseParser.run_safe),
    # и падение биржи не должно останавливать доставку и бота.
    bot_task = asyncio.create_task(dp.start_polling(bot), name="bot")

    tasks = [
        bot_task,
        asyncio.create_task(heartbeat.run(), name="heartbeat"),
        # Сверка состава парсеров с выбором пользователей: включённая в боте
        # биржа стартует без перезапуска процесса.
        asyncio.create_task(supervisor.run(), name="sources"),
        *[
            # Несколько потребителей очереди: пока один ждёт ответа модели,
            # остальные разбирают следующие лиды. Записи в SQLite всё равно
            # сериализуются, а INSERT OR IGNORE делает гонку дедупликации
            # безопасной, поэтому параллелизм тут выигрышный.
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
                name=f"processor-{index}",
            )
            for index in range(max(1, settings.pipeline_workers))
        ],
    ]

    stop = asyncio.Event()
    _install_signal_handlers(stop)

    try:
        # Ждём либо сигнала остановки, либо падения любой из задач: если умер
        # поллинг бота, продолжать работу смысла нет — пусть перезапустит Docker.
        waiter = asyncio.create_task(stop.wait(), name="stop-signal")
        done, _ = await asyncio.wait(
            [bot_task, waiter], return_when=asyncio.FIRST_COMPLETED
        )
        waiter.cancel()
        for task in done:
            if task is not waiter and not task.cancelled():
                exc = task.exception()
                if exc is not None:
                    log.error("Задача %s упала: %s", task.get_name(), exc)
    finally:
        log.info("Остановка LeadHunter…")
        for task in tasks:
            task.cancel()
        # Дожидаемся отмены, иначе задачи продолжат жить на закрытых ресурсах.
        await asyncio.gather(*tasks, return_exceptions=True)
        await _quiet(supervisor.aclose())
        await _quiet(responder.aclose())
        await _quiet(db.close())
        await _quiet(bot.session.close())


def check_configuration(settings: Settings) -> list[str]:
    """Проверяет минимально необходимые настройки перед запуском."""
    problems: list[str] = []

    token = settings.bot_token.strip()
    if not token:
        problems.append(
            "BOT_TOKEN пуст. Получите токен у @BotFather и впишите его в .env"
        )
    elif ":" not in token or not token.split(":", 1)[0].isdigit():
        problems.append(
            "BOT_TOKEN не похож на токен Telegram (ожидается вид 123456:AA...). "
            "Проверьте, что скопирован он целиком"
        )

    if not settings.owner_id and not settings.dev_mode:
        problems.append(
            "OWNER_ID не задан — бот никого не пустит и админ-панель будет "
            "недоступна. Узнать свой ID: @userinfobot"
        )

    problems.extend(_check_writable(settings.database_file.parent, "базы данных"))

    return problems


def _check_writable(directory, what: str) -> list[str]:
    """Проверяет, что в каталог можно писать.

    Частый случай на чистом VPS: каталог data/ создан Docker'ом от root, а
    контейнер работает от непривилегированного пользователя. Без этой проверки
    покупатель увидел бы невнятную ошибку SQLite вместо понятной причины.
    """
    try:
        directory.mkdir(parents=True, exist_ok=True)
        probe = directory / ".write-test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
    except OSError as exc:
        return [
            f"Каталог {what} недоступен на запись: {directory} ({exc.strerror}). "
            f"Исправить: sudo chown -R 10001:10001 {directory}"
        ]
    return []


def _install_signal_handlers(stop: asyncio.Event) -> None:
    """Просит цикл остановиться по SIGTERM/SIGINT.

    Без этого `docker stop` убивал бы процесс мгновенно, не дав закрыть базу и
    сетевые соединения. На платформах без add_signal_handler (Windows) молча
    остаёмся на поведении по умолчанию.
    """
    loop = asyncio.get_running_loop()
    for name in ("SIGTERM", "SIGINT"):
        sig = getattr(signal, name, None)
        if sig is None:
            continue
        try:
            loop.add_signal_handler(sig, stop.set)
        except (NotImplementedError, RuntimeError):
            log.debug("Сигнал %s не перехватывается на этой платформе", name)


async def _quiet(awaitable) -> None:
    """Закрывает ресурс, не позволяя сбою одного помешать остальным."""
    try:
        await awaitable
    except Exception:  # noqa: BLE001 — при остановке важно закрыть всё
        log.debug("Ошибка при закрытии ресурса", exc_info=True)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        pass

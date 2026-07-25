"""kwork_bot — точка входа (composition root).

Собирает зависимости (DI), запускает фоновые воркеры через `asyncio.TaskGroup`,
корректно завершается по SIGTERM/SIGINT: останавливает polling и очередь доставки,
закрывает Playwright, освобождает сессию бота и движок БД. Пишет heartbeat для
Docker HEALTHCHECK.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import signal

from ai.gemini_client import GeminiClient
from config.settings import get_settings
from database.session import Database
from parsers.browser import BrowserManager
from parsers.kwork_parser import KworkParser
from schemas.filters import FilterConfig
from security.license_service import LicenseVerifier
from services.filtering import LeadFilter
from services.lead_service import LeadService
from services.response_service import ResponseService
from telegram.bot import build_bot, build_dispatcher
from telegram.delivery import DeliveryService
from utils.healthcheck import Healthcheck
from utils.logging import setup_logging

log = logging.getLogger("kwork_bot")

_HEARTBEAT_INTERVAL = 30.0


def _install_signal_handlers(loop: asyncio.AbstractEventLoop, stop_event: asyncio.Event) -> None:
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, stop_event.set)
        except NotImplementedError:  # pragma: no cover - Windows
            signal.signal(sig, lambda *_: stop_event.set())


async def _wait_or_stop(stop_event: asyncio.Event, timeout: float) -> None:
    with contextlib.suppress(asyncio.TimeoutError):
        await asyncio.wait_for(stop_event.wait(), timeout=timeout)


async def _run_polling(dp, bot, stop_event: asyncio.Event) -> None:
    polling = asyncio.create_task(dp.start_polling(bot, handle_signals=False))
    await stop_event.wait()
    await dp.stop_polling()
    with contextlib.suppress(Exception):
        await polling


async def _poll_loop(
    lead_service: LeadService,
    healthcheck: Healthcheck,
    interval: int,
    stop_event: asyncio.Event,
) -> None:
    while not stop_event.is_set():
        try:
            await lead_service.process_once()
        except Exception:  # noqa: BLE001 — сбой прохода не останавливает цикл
            log.exception("Ошибка прохода парсинга")
        healthcheck.beat()
        await _wait_or_stop(stop_event, interval)


async def _heartbeat_loop(healthcheck: Healthcheck, stop_event: asyncio.Event) -> None:
    while not stop_event.is_set():
        healthcheck.beat()
        await _wait_or_stop(stop_event, _HEARTBEAT_INTERVAL)


async def run() -> None:
    settings = get_settings()
    setup_logging(settings.log_level, settings.log_dir)
    log.info("Запуск kwork_bot…")

    # 1. Лицензия — обязательная проверка на старте.
    verifier = LicenseVerifier(settings)
    status = verifier.verify()
    if not status.valid:
        log.error("Лицензия недействительна: %s. Останов.", status.reason)
        return
    log.info("Лицензия действительна: %s", status.license_key or "—")

    # 2. Сборка зависимостей (DI).
    database = Database(settings.database_url, echo=settings.db_echo, sqlite_path=settings.database_path)
    gemini = GeminiClient(settings)
    response_service = ResponseService(gemini)
    lead_filter = LeadFilter(FilterConfig.from_yaml(settings.filters_path))
    healthcheck = Healthcheck(settings.healthcheck_file, max_age=settings.kwork_poll_interval * 3 + 60)
    bot = build_bot(settings)
    delivery = DeliveryService(
        bot=bot,
        database=database,
        owner_id=settings.owner_id,
        retry_attempts=settings.retry_attempts,
        retry_base_delay=settings.retry_base_delay,
        retry_max_delay=settings.retry_max_delay,
    )
    dp = build_dispatcher(
        settings=settings,
        database=database,
        response_service=response_service,
        license_verifier=verifier,
    )

    stop_event = asyncio.Event()
    _install_signal_handlers(asyncio.get_running_loop(), stop_event)

    # 3. Запуск фоновых воркеров и graceful shutdown.
    browser = BrowserManager(settings)
    try:
        await browser.start()
        parser = KworkParser(browser, settings.kwork_url)
        lead_service = LeadService(
            database=database,
            source=parser,
            lead_filter=lead_filter,
            response_service=response_service,
            deliverer=delivery,
        )
        healthcheck.beat()
        log.info("kwork_bot запущен. Опрос Kwork каждые %s c.", settings.kwork_poll_interval)

        async with asyncio.TaskGroup() as task_group:
            task_group.create_task(_run_polling(dp, bot, stop_event), name="tg-polling")
            task_group.create_task(delivery.worker(stop_event), name="delivery")
            task_group.create_task(
                _poll_loop(lead_service, healthcheck, settings.kwork_poll_interval, stop_event),
                name="kwork-poll",
            )
            task_group.create_task(_heartbeat_loop(healthcheck, stop_event), name="heartbeat")

        log.info("Все воркеры остановлены.")
    finally:
        await browser.stop()
        with contextlib.suppress(Exception):
            await bot.session.close()
        await database.dispose()
        log.info("kwork_bot остановлен.")


def main() -> None:
    try:
        asyncio.run(run())
    except KeyboardInterrupt:  # pragma: no cover
        pass


if __name__ == "__main__":
    main()

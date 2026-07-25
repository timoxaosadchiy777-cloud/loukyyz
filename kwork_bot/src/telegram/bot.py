"""Сборка бота и диспетчера aiogram 3.x.

Middlewares регистрируются в порядке: license → ratelimit → dedup (на message и
callback_query). Глобальный error-handler логирует исключения хендлеров, чтобы
polling не падал.
"""

from __future__ import annotations

import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import ErrorEvent

from config.settings import Settings
from database.session import Database
from security.license_service import LicenseVerifier
from services.response_service import ResponseService
from telegram.middlewares import DedupMiddleware, LicenseMiddleware, RateLimitMiddleware
from telegram.routers import leads_router

log = logging.getLogger(__name__)


def build_bot(settings: Settings) -> Bot:
    return Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )


def build_dispatcher(
    *,
    settings: Settings,
    database: Database,
    response_service: ResponseService,
    license_verifier: LicenseVerifier,
) -> Dispatcher:
    dp = Dispatcher()

    # Зависимости хендлеров (внедряются по имени аргумента).
    dp["database"] = database
    dp["response_service"] = response_service
    dp["owner_id"] = settings.owner_id

    # Middlewares строго в требуемом порядке: license → ratelimit → dedup.
    for observer in (dp.message, dp.callback_query):
        observer.middleware(LicenseMiddleware(license_verifier))
        observer.middleware(RateLimitMiddleware())
        observer.middleware(DedupMiddleware())

    dp.include_router(leads_router)

    @dp.errors()
    async def _on_error(event: ErrorEvent) -> bool:
        log.exception("Ошибка обработки апдейта: %s", event.exception)
        return True  # помечаем обработанной — polling продолжается

    return dp

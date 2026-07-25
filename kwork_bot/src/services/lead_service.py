"""Главный оркестратор пайплайна заказов.

    KworkParser → LeadService → dedup → filter → GeminiClient → DeliveryService → Telegram

Работает только через репозитории (не касается SQLAlchemy напрямую) и абстракции
(`LeadSource`, `LeadDeliverer`); все зависимости приходят через конструктор (DI).
Telegram-логики здесь нет.
"""

from __future__ import annotations

import logging

from sqlalchemy.exc import IntegrityError

from database.repositories.lead_repo import LeadRepository
from database.session import Database
from schemas.lead import LeadCreate, LeadRead
from services.filtering import LeadFilter
from services.interfaces import LeadDeliverer, LeadSource
from services.response_service import ResponseService

log = logging.getLogger(__name__)


class LeadService:
    """Оркестрирует сбор, дедупликацию, фильтрацию, генерацию и доставку заказов."""

    def __init__(
        self,
        *,
        database: Database,
        source: LeadSource,
        lead_filter: LeadFilter,
        response_service: ResponseService,
        deliverer: LeadDeliverer,
    ) -> None:
        self._database = database
        self._source = source
        self._filter = lead_filter
        self._responses = response_service
        self._deliverer = deliverer

    async def process_once(self) -> int:
        """Один проход пайплайна. Возвращает число заказов, ушедших в доставку."""
        leads = await self._source.fetch_leads()
        delivered = 0
        for data in leads:
            try:
                if await self._handle_lead(data):
                    delivered += 1
            except Exception:  # noqa: BLE001 — сбой одного заказа не рушит проход
                log.exception("Ошибка обработки заказа %s:%s", data.source, data.external_id)
        log.info("Проход завершён: получено %s, отправлено в доставку %s", len(leads), delivered)
        return delivered

    async def _handle_lead(self, data: LeadCreate) -> bool:
        # 1. Дедуп + фильтр + создание записи (атомарно в одной транзакции).
        try:
            async with self._database.session() as session:
                repo = LeadRepository(session)

                if await repo.exists(data.source, data.external_id):
                    log.debug("Дубликат пропущен: %s", data.external_id)
                    return False

                verdict = self._filter.check(data)
                if not verdict.passed:
                    await repo.create(data, status="filtered")
                    log.info("Отфильтрован %s: %s", data.external_id, verdict.reason)
                    return False

                lead = await repo.create(data, status="new")
                lead_read = LeadRead.model_validate(lead)
        except IntegrityError:
            # Гонка: тот же заказ вставлен параллельным проходом.
            log.debug("Дубликат при вставке (гонка): %s", data.external_id)
            return False

        # 2. Генерация отклика (вне транзакции — сетевой вызов ИИ).
        response = await self._responses.generate(data)

        # 3. Сохранение отклика (если получен).
        if response:
            async with self._database.session() as session:
                await LeadRepository(session).set_response(lead_read.id, response)

        # 4. Доставка (антидубль и очередь — внутри DeliveryService).
        await self._deliverer.enqueue(lead_read, response)
        log.info("Заказ %s передан в доставку", data.external_id)
        return True

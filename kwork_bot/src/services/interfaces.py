"""Интерфейсы (Protocol) для развязки бизнес-логики от инфраструктуры.

`LeadService` зависит от этих абстракций, а не от конкретных Playwright/Telegram —
это удерживает бизнес-слой чистым и тестируемым (DI через конструкторы).
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from schemas.lead import LeadCreate, LeadRead


@runtime_checkable
class LeadSource(Protocol):
    """Источник заказов (реализуется парсером)."""

    async def fetch_leads(self) -> list[LeadCreate]:
        ...


@runtime_checkable
class LeadDeliverer(Protocol):
    """Доставщик готовых карточек (реализуется Telegram DeliveryService)."""

    async def enqueue(self, lead: LeadRead, response: str | None) -> None:
        ...

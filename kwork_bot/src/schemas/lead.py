"""Pydantic-схемы заказа (валидация на границах слоёв)."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class LeadBase(BaseModel):
    """Общие поля заказа."""

    source: str = Field(min_length=1, max_length=32)
    external_id: str = Field(min_length=1, max_length=128)
    title: str = Field(min_length=1, max_length=512)
    url: str = Field(min_length=1, max_length=1024)
    description: str = ""
    budget_raw: str = ""
    budget_value: int | None = None


class LeadCreate(LeadBase):
    """Данные для создания заказа (из парсера)."""


class LeadRead(LeadBase):
    """Представление заказа из БД."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    status: str
    response_text: str | None = None
    created_at: datetime

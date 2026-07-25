"""Pydantic-схема конфигурации фильтров (валидация `filters.yaml`)."""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, Field, field_validator


class FilterConfig(BaseModel):
    """Правила отбора заказов, загружаемые из YAML."""

    keywords: list[str] = Field(default_factory=list)
    stop_words: list[str] = Field(default_factory=list)
    min_budget: int = 0

    @field_validator("keywords", "stop_words", mode="before")
    @classmethod
    def _normalize(cls, value: object) -> object:
        if value is None:
            return []
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        return value

    @classmethod
    def from_yaml(cls, path: str | Path) -> "FilterConfig":
        """Загружает и валидирует конфигурацию фильтров из YAML-файла."""
        file_path = Path(path)
        if not file_path.exists():
            return cls()
        raw = yaml.safe_load(file_path.read_text(encoding="utf-8")) or {}
        return cls.model_validate(raw)

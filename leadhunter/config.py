"""Централизованная конфигурация LeadHunter.

Все настройки читаются из переменных окружения / `.env` через pydantic-settings.
Единственный источник правды для секретов и параметров запуска.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Annotated

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

# Списки читаем из CSV-строк окружения (`a, b, c`), а не из JSON — так удобнее
# заполнять `.env` вручную. NoDecode отключает попытку pydantic распарсить JSON.
CsvList = Annotated[list[str], NoDecode]


class Settings(BaseSettings):
    """Настройки приложения, загружаемые из окружения."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- Aiogram-бот (доставка карточек владельцу) ---
    bot_token: str = Field("", alias="BOT_TOKEN")
    owner_id: int = Field(0, alias="OWNER_ID")

    # --- Google Gemini (генерация откликов) ---
    gemini_api_key: str = Field("", alias="GEMINI_API_KEY")
    gemini_model: str = Field("gemini-2.5-flash", alias="GEMINI_MODEL")
    gemini_max_tokens: int = Field(1024, alias="GEMINI_MAX_TOKENS")
    gemini_temperature: float = Field(0.7, alias="GEMINI_TEMPERATURE")

    # --- Устойчивость: ретраи и алёрты ---
    retry_attempts: int = Field(3, alias="RETRY_ATTEMPTS")
    retry_base_delay: float = Field(2.0, alias="RETRY_BASE_DELAY")
    alert_cooldown: int = Field(300, alias="ALERT_COOLDOWN")

    # --- Kwork (Playwright-парсер) ---
    kwork_enabled: bool = Field(True, alias="KWORK_ENABLED")
    kwork_url: str = Field("https://kwork.ru/projects", alias="KWORK_URL")
    kwork_poll_interval: int = Field(180, alias="KWORK_POLL_INTERVAL")
    kwork_headless: bool = Field(True, alias="KWORK_HEADLESS")
    # Файл сохранённой сессии браузера (создаётся скриптом kwork_login.py).
    kwork_storage_state: str = Field("storage_state.json", alias="KWORK_STORAGE_STATE")

    # --- Фильтрация мусора ---
    min_budget: int = Field(2000, alias="MIN_BUDGET")
    junk_phrases: CsvList = Field(
        default_factory=lambda: [
            "за отзыв",
            "за отзывы",
            "бесплатно",
            "за лайк",
            "за репост",
            "тестовое бесплатно",
        ],
        alias="JUNK_PHRASES",
    )

    # --- Прочее ---
    database_path: str = Field("leadhunter.db", alias="DATABASE_PATH")
    log_level: str = Field("INFO", alias="LOG_LEVEL")

    @field_validator("junk_phrases", mode="before")
    @classmethod
    def _split_csv(cls, value: object) -> object:
        """Позволяет задавать список одной строкой: `a, b, c`."""
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @property
    def gemini_ready(self) -> bool:
        return bool(self.gemini_api_key)


@lru_cache
def get_settings() -> Settings:
    """Singleton-доступ к настройкам (кэшируется на всё время работы процесса)."""
    return Settings()

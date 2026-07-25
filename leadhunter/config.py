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
    gemini_model: str = Field("gemini-1.5-flash", alias="GEMINI_MODEL")
    gemini_max_tokens: int = Field(1024, alias="GEMINI_MAX_TOKENS")
    gemini_temperature: float = Field(0.7, alias="GEMINI_TEMPERATURE")

    # --- Устойчивость: ретраи и алёрты ---
    retry_attempts: int = Field(3, alias="RETRY_ATTEMPTS")
    retry_base_delay: float = Field(2.0, alias="RETRY_BASE_DELAY")
    alert_cooldown: int = Field(300, alias="ALERT_COOLDOWN")

    # --- Источники лидов (RSS/Atom международных площадок) ---
    # Список фидов через запятую. По умолчанию — публичные джоб-борды удалёнки;
    # для Upwork добавьте URL вашего saved-search RSS.
    feeds: CsvList = Field(
        default_factory=lambda: [
            "https://weworkremotely.com/categories/remote-programming-jobs.rss",
            "https://remoteok.com/remote-python-jobs.rss",
        ],
        alias="FEEDS",
    )
    feed_poll_interval: int = Field(300, alias="FEED_POLL_INTERVAL")

    # --- AI Lead Scoring ---
    # Профиль исполнителя: ИИ читает его и по смыслу оценивает заказы.
    profile_path: str = Field("profile.md", alias="PROFILE_PATH")
    # Оперативные настройки (min_score / min_budget / enabled_sources) — правятся
    # на ходу в этом YAML, без перезапуска (см. core/runtime_config.py).
    runtime_config_path: str = Field("settings.yaml", alias="RUNTIME_CONFIG_PATH")

    # --- Прочее ---
    database_path: str = Field("leadhunter.db", alias="DATABASE_PATH")
    log_level: str = Field("INFO", alias="LOG_LEVEL")

    @field_validator("feeds", mode="before")
    @classmethod
    def _split_csv(cls, value: object) -> object:
        """Позволяет задавать списки одной строкой: `a, b, c`."""
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

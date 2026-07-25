"""Настройки kwork_bot, читаемые из окружения / `.env` (pydantic-settings v2).

Единственный источник правды для секретов и параметров запуска. Секреты в коде
не хранятся — только в `.env` (см. `.env.example`).
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Корень src (…/kwork_bot/src) — для дефолтных относительных путей.
_SRC_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    """Строго типизированные настройки приложения."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- Telegram (Aiogram Bot API) ---
    bot_token: str = Field("", alias="BOT_TOKEN")
    owner_id: int = Field(0, alias="OWNER_ID")

    # --- Google Gemini ---
    gemini_api_key: str = Field("", alias="GEMINI_API_KEY")
    gemini_model: str = Field("gemini-1.5-flash", alias="GEMINI_MODEL")
    gemini_fallback_model: str = Field("gemini-2.5-flash", alias="GEMINI_FALLBACK_MODEL")
    gemini_max_tokens: int = Field(1024, alias="GEMINI_MAX_TOKENS")
    gemini_temperature: float = Field(0.7, alias="GEMINI_TEMPERATURE")
    gemini_rps: float = Field(0.5, alias="GEMINI_RPS")  # запросов в секунду

    # --- Ретраи ---
    retry_attempts: int = Field(4, alias="RETRY_ATTEMPTS")
    retry_base_delay: float = Field(2.0, alias="RETRY_BASE_DELAY")
    retry_max_delay: float = Field(30.0, alias="RETRY_MAX_DELAY")

    # --- Kwork (Playwright) ---
    kwork_url: str = Field("https://kwork.ru/projects", alias="KWORK_URL")
    kwork_poll_interval: int = Field(180, alias="KWORK_POLL_INTERVAL")
    kwork_headless: bool = Field(True, alias="KWORK_HEADLESS")
    kwork_nav_timeout_ms: int = Field(30000, alias="KWORK_NAV_TIMEOUT_MS")
    kwork_storage_state: Path = Field(
        default=_SRC_ROOT.parent / "data" / "storage_state.json",
        alias="KWORK_STORAGE_STATE",
    )

    # --- Лицензия (коммерческая защита, Ed25519) ---
    license_key: str = Field("", alias="LICENSE_KEY")
    license_public_key: str = Field("", alias="LICENSE_PUBLIC_KEY")  # base64 Ed25519 pubkey
    license_cache_ttl: int = Field(86400, alias="LICENSE_CACHE_TTL")  # сек

    # --- Фильтры ---
    filters_path: Path = Field(
        default=_SRC_ROOT / "config" / "filters.yaml",
        alias="FILTERS_PATH",
    )

    # --- База данных (SQLite WAL) ---
    database_path: Path = Field(
        default=_SRC_ROOT.parent / "data" / "kwork_bot.db",
        alias="DATABASE_PATH",
    )
    db_echo: bool = Field(False, alias="DB_ECHO")

    # --- Логирование / инфраструктура ---
    log_level: str = Field("INFO", alias="LOG_LEVEL")
    log_dir: Path = Field(default=_SRC_ROOT.parent / "logs", alias="LOG_DIR")
    healthcheck_file: Path = Field(
        default=_SRC_ROOT.parent / "data" / "healthcheck.txt",
        alias="HEALTHCHECK_FILE",
    )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def database_url(self) -> str:
        """Async-URL SQLAlchemy для SQLite (aiosqlite)."""
        return f"sqlite+aiosqlite:///{self.database_path}"

    @property
    def gemini_ready(self) -> bool:
        return bool(self.gemini_api_key)

    @property
    def license_configured(self) -> bool:
        return bool(self.license_key and self.license_public_key)


@lru_cache
def get_settings() -> Settings:
    """Singleton-доступ к настройкам (кэшируется на весь процесс)."""
    return Settings()

"""Централизованная конфигурация LeadHunter.

Все настройки читаются из переменных окружения / `.env` через pydantic-settings.
Единственный источник правды для секретов и параметров запуска.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Annotated

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

# Корень проекта = каталог с этим файлом. Относительные пути (profile.md,
# settings.yaml, leadhunter.db) резолвим ОТНОСИТЕЛЬНО него, а не текущего рабочего
# каталога — иначе запуск `python leadhunter/main.py` из корня репозитория не
# находит profile.md/settings.yaml (симптом «файл не найден»).
BASE_DIR = Path(__file__).resolve().parent

# Списки читаем из CSV-строк окружения (`a, b, c`), а не из JSON — так удобнее
# заполнять `.env` вручную. NoDecode отключает попытку pydantic распарсить JSON.
CsvList = Annotated[list[str], NoDecode]


def resolve_path(path: str) -> Path:
    """Возвращает абсолютный путь: как есть, если абсолютный, иначе от BASE_DIR."""
    candidate = Path(path).expanduser()
    return candidate if candidate.is_absolute() else BASE_DIR / candidate


class Settings(BaseSettings):
    """Настройки приложения, загружаемые из окружения."""

    # .env берём по абсолютному пути от каталога проекта, а не от текущего рабочего
    # каталога — иначе `python leadhunter/main.py` из корня репозитория не подхватит
    # leadhunter/.env, и ключи (в т.ч. GEMINI_API_KEY) окажутся пустыми.
    # Реальные переменные окружения по-прежнему имеют приоритет над файлом.
    model_config = SettingsConfigDict(
        env_file=(str(BASE_DIR / ".env"), ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- Aiogram-бот (доставка карточек владельцу) ---
    bot_token: str = Field("", alias="BOT_TOKEN")
    owner_id: int = Field(0, alias="OWNER_ID")

    # --- AI-провайдеры (скоринг и генерация откликов) ---
    # Основной провайдер. Порядок fallback фиксирован: openrouter → groq → ollama
    # → gemini; выбранный здесь встаёт первым. Значения: openrouter/groq/ollama/gemini.
    ai_provider: str = Field("openrouter", alias="AI_PROVIDER")

    # OpenRouter (основной, бесплатные модели) — https://openrouter.ai/keys
    openrouter_api_key: str = Field("", alias="OPENROUTER_API_KEY")
    openrouter_model: str = Field("deepseek/deepseek-chat:free", alias="OPENROUTER_MODEL")

    # Groq (быстрый бесплатный fallback) — https://console.groq.com/keys
    groq_api_key: str = Field("", alias="GROQ_API_KEY")
    groq_model: str = Field("llama-3.3-70b-versatile", alias="GROQ_MODEL")

    # Ollama (локальные модели). По умолчанию выключен — включите, если установлен.
    ollama_enabled: bool = Field(False, alias="OLLAMA_ENABLED")
    ollama_host: str = Field("http://localhost:11434", alias="OLLAMA_HOST")
    ollama_model: str = Field("llama3.2", alias="OLLAMA_MODEL")

    # Gemini (крайний fallback, если есть рабочий ключ) — одна модель, без внутр. fallback.
    gemini_api_key: str = Field("", alias="GEMINI_API_KEY")
    gemini_model: str = Field("gemini-2.0-flash", alias="GEMINI_MODEL")

    # Общие параметры генерации (для всех провайдеров).
    ai_max_tokens: int = Field(1024, alias="AI_MAX_TOKENS")
    ai_temperature: float = Field(0.7, alias="AI_TEMPERATURE")

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

    # --- Kwork (kwork.ru и kwork.com) ---
    # Выключен по умолчанию: без явного включения ничего не парсим.
    kwork_enabled: bool = Field(False, alias="KWORK_ENABLED")
    kwork_ru_url: str = Field("https://kwork.ru", alias="KWORK_RU_URL")
    kwork_com_url: str = Field("https://kwork.com", alias="KWORK_COM_URL")
    kwork_projects_path: str = Field("/projects", alias="KWORK_PROJECTS_PATH")
    # Сессионная кука: без неё видна только публичная выдача (лидов меньше).
    # Как получить — см. README, раздел «Kwork».
    kwork_cookie: str = Field("", alias="KWORK_COOKIE")
    kwork_com_cookie: str = Field("", alias="KWORK_COM_COOKIE")
    kwork_poll_interval: int = Field(300, alias="KWORK_POLL_INTERVAL")
    kwork_pages: int = Field(1, alias="KWORK_PAGES")
    kwork_timeout: float = Field(20.0, alias="KWORK_TIMEOUT")

    # Курс для приведения рублёвых бюджетов к порогу в долларах. Приблизительный:
    # нужен только для отсечки, в карточке всегда показана исходная сумма.
    usd_rub_rate: float = Field(95.0, alias="USD_RUB_RATE")

    # --- AI Lead Scoring ---
    # Профиль исполнителя: ИИ читает его и по смыслу оценивает заказы.
    profile_path: str = Field("profile.md", alias="PROFILE_PATH")
    # Оперативные настройки (min_score / min_budget / enabled_sources) — правятся
    # на ходу в этом YAML, без перезапуска (см. core/runtime_config.py).
    runtime_config_path: str = Field("settings.yaml", alias="RUNTIME_CONFIG_PATH")

    # --- Прочее ---
    database_path: str = Field("leadhunter.db", alias="DATABASE_PATH")
    log_level: str = Field("INFO", alias="LOG_LEVEL")
    # Файл лога с ротацией. Пусто = только stdout (docker logs / journald).
    log_file: str = Field("", alias="LOG_FILE")
    log_max_bytes: int = Field(10 * 1024 * 1024, alias="LOG_MAX_BYTES")
    log_backups: int = Field(5, alias="LOG_BACKUPS")

    # Файл-биение для healthcheck: обновляется, пока жив event loop.
    health_file: str = Field("data/health", alias="HEALTH_FILE")
    health_interval: int = Field(30, alias="HEALTH_INTERVAL")
    # Очередь ограничена намеренно: если ИИ тормозит, парсеры притормозят вместе
    # с ним, а не будут набивать память лидами до OOM.
    queue_maxsize: int = Field(1000, alias="QUEUE_MAXSIZE")

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

    # Абсолютные пути — устойчивы к текущему рабочему каталогу.
    @property
    def profile_file(self) -> Path:
        return resolve_path(self.profile_path)

    @property
    def runtime_config_file(self) -> Path:
        return resolve_path(self.runtime_config_path)

    @property
    def database_file(self) -> Path:
        return resolve_path(self.database_path)

    @property
    def health_path(self) -> Path:
        return resolve_path(self.health_file)

    @property
    def log_path(self) -> Path | None:
        return resolve_path(self.log_file) if self.log_file else None


@lru_cache
def get_settings() -> Settings:
    """Singleton-доступ к настройкам (кэшируется на всё время работы процесса)."""
    return Settings()

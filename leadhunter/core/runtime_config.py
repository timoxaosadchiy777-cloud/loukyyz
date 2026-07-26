"""Оперативные настройки, изменяемые без правки кода и перезапуска.

`min_score`, `min_budget` и `enabled_sources` живут в YAML-файле (`settings.yaml`),
который можно редактировать на ходу: изменения подхватываются автоматически на
следующем заказе (перезагрузка по mtime). Файл создаётся при первом запуске из
значений по умолчанию; если он отсутствует или повреждён — используются дефолты.

Секреты и параметры окружения (токены, ключи, фиды) остаются в `.env`
(см. `config.py`); здесь — только «крутилки» повседневной эксплуатации.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

import yaml

log = logging.getLogger(__name__)

# Известные источники лидов (для валидации enabled_sources).
ALL_SOURCES: tuple[str, ...] = ("upwork", "fiverr", "rss")

# Локальный, бесплатный провайдер по умолчанию — без ключей и платных API.
_DEFAULT_LLM_PROVIDER = "ollama"
_DEFAULT_LLM_MODEL = "llama3.1:8b"
_DEFAULT_LLM_BASE_URL = "http://localhost:11434"


@dataclass(frozen=True, slots=True)
class LlmConfig:
    """Настройки LLM-провайдера (правятся в settings.yaml, блок `llm:`).

    По умолчанию — локальный Ollama: без API-ключей и платных сервисов.
    """

    provider: str = _DEFAULT_LLM_PROVIDER
    model: str = _DEFAULT_LLM_MODEL
    base_url: str = _DEFAULT_LLM_BASE_URL


@dataclass(frozen=True, slots=True)
class RuntimeConfig:
    """Снимок оперативных настроек.

    Attributes:
        min_score: Минимальный AI Score (0..100), при котором заказ доходит до
            владельца. Заказы ниже порога отсеиваются после оценки ИИ.
        min_budget: Дешёвый предварительный фильтр по бюджету (USD) — применяется
            ДО обращения к LLM, чтобы не тратить запросы на заведомо мелочь.
        enabled_sources: Активные источники. Пустой список = разрешены все.
        llm: Настройки LLM-провайдера (по умолчанию локальный Ollama).
    """

    min_score: int = 60
    min_budget: int = 50
    enabled_sources: tuple[str, ...] = field(default_factory=lambda: ALL_SOURCES)
    llm: LlmConfig = field(default_factory=LlmConfig)

    def source_enabled(self, source: str) -> bool:
        """Разрешён ли источник (пустой список источников = разрешены все)."""
        return not self.enabled_sources or source in self.enabled_sources


_TEMPLATE = """\
# ============================================================
#  LeadHunter — оперативные настройки (правьте на ходу).
#  Файл перечитывается автоматически, перезапуск не нужен.
# ============================================================

# Минимальный AI Score (0..100): заказы с оценкой ниже не доходят до Telegram.
min_score: {min_score}

# Предварительный фильтр по бюджету (USD): заказы с распознанной суммой ниже
# отсекаются ещё ДО обращения к ИИ (экономия запросов). Лиды без явной суммы
# проходят дальше и оцениваются ИИ.
min_budget: {min_budget}

# Активные источники лидов. Уберите ненужные; пустой список [] = все источники.
# Возможные значения: {all_sources}
enabled_sources: [{sources}]

# LLM-провайдер. По умолчанию — локальный Ollama: бесплатно, без API-ключей.
# Установка: https://ollama.com/download , затем `ollama pull {llm_model}`.
llm:
  provider: {llm_provider}
  model: {llm_model}
  base_url: {llm_base_url}
"""


class RuntimeConfigStore:
    """Загрузчик оперативных настроек из YAML с горячей перезагрузкой по mtime."""

    def __init__(self, path: str | Path, *, defaults: RuntimeConfig | None = None) -> None:
        self._path = Path(path)
        self._defaults = defaults or RuntimeConfig()
        self._cached = self._defaults
        self._mtime: float | None = None
        self._ensure_file()
        self.reload()

    def current(self) -> RuntimeConfig:
        """Актуальные настройки; при изменении файла — перечитывает его."""
        try:
            mtime = self._path.stat().st_mtime
        except OSError:
            return self._cached
        if mtime != self._mtime:
            self.reload()
        return self._cached

    def reload(self) -> RuntimeConfig:
        """Принудительно перечитывает файл настроек и кэширует результат."""
        try:
            mtime = self._path.stat().st_mtime
            text = self._path.read_text(encoding="utf-8")
        except OSError:
            self._cached = self._defaults
            return self._cached

        try:
            data = yaml.safe_load(text) or {}
        except yaml.YAMLError as exc:
            log.warning("settings.yaml повреждён (%s) — использую предыдущие/дефолтные значения", exc)
            self._mtime = mtime  # не перечитывать битый файл в цикле
            return self._cached

        if not isinstance(data, dict):
            log.warning("settings.yaml: ожидался объект настроек — использую дефолты")
            data = {}

        self._cached = self._build(data)
        self._mtime = mtime
        log.info(
            "Настройки: min_score=%s, min_budget=%s, sources=%s, llm=%s/%s",
            self._cached.min_score,
            self._cached.min_budget,
            ",".join(self._cached.enabled_sources) or "все",
            self._cached.llm.provider,
            self._cached.llm.model,
        )
        return self._cached

    def _build(self, data: dict) -> RuntimeConfig:
        d = self._defaults
        return RuntimeConfig(
            min_score=_as_int(data.get("min_score"), d.min_score, low=0, high=100),
            min_budget=_as_int(data.get("min_budget"), d.min_budget, low=0),
            enabled_sources=_as_sources(data.get("enabled_sources"), d.enabled_sources),
            llm=_as_llm(data.get("llm"), d.llm),
        )

    def _ensure_file(self) -> None:
        if self._path.exists():
            return
        d = self._defaults
        content = _TEMPLATE.format(
            min_score=d.min_score,
            min_budget=d.min_budget,
            all_sources=", ".join(ALL_SOURCES),
            sources=", ".join(d.enabled_sources),
            llm_provider=d.llm.provider,
            llm_model=d.llm.model,
            llm_base_url=d.llm.base_url,
        )
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(content, encoding="utf-8")
            log.info("Создан файл настроек %s (значения по умолчанию)", self._path)
        except OSError as exc:
            log.warning("Не удалось создать %s: %s — работаю на дефолтах", self._path, exc)


# --- Валидация значений (мягкая: неверное значение → дефолт с предупреждением) ---

def _as_int(value: object, default: int, *, low: int | None = None, high: int | None = None) -> int:
    try:
        result = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        if value is not None:
            log.warning("Настройка %r не число — использую %s", value, default)
        return default
    if low is not None and result < low:
        return low
    if high is not None and result > high:
        return high
    return result


def _as_llm(value: object, default: LlmConfig) -> LlmConfig:
    """Разбирает блок `llm:` из settings.yaml (мягко, с падением на дефолты)."""
    if value is None:
        return default
    if not isinstance(value, dict):
        log.warning("settings.yaml: блок 'llm' должен быть объектом — использую дефолты")
        return default

    def _text(key: str, fallback: str) -> str:
        raw = value.get(key)
        if raw is None:
            return fallback
        text = str(raw).strip()
        return text or fallback

    return LlmConfig(
        provider=_text("provider", default.provider).lower(),
        model=_text("model", default.model),
        base_url=_text("base_url", default.base_url).rstrip("/"),
    )


def _as_sources(value: object, default: tuple[str, ...]) -> tuple[str, ...]:
    if value is None:
        return default
    if isinstance(value, str):
        items = [value]
    elif isinstance(value, (list, tuple)):
        items = list(value)
    else:
        log.warning("enabled_sources: неверный формат — использую %s", default)
        return default

    cleaned: list[str] = []
    for item in items:
        name = str(item).strip().lower()
        if not name:
            continue
        if name not in ALL_SOURCES:
            log.warning("enabled_sources: неизвестный источник %r пропущен", name)
            continue
        if name not in cleaned:
            cleaned.append(name)
    # Пустой список считаем осознанным «разрешить все».
    return tuple(cleaned)

"""Сборка парсеров по реестру источников.

Единственное место, которое знает, как из :data:`core.sources.SOURCES` получить
работающие парсеры. Фабрики импортируются лениво по строке ``"модуль:функция"``,
поэтому источник с тяжёлыми зависимостями не мешает запуску, пока он выключен.

Отказ одного источника не должен ронять остальные: не импортировался модуль,
не хватило настроек, упала фабрика — пишем в лог, пропускаем, идём дальше.
"""

from __future__ import annotations

import asyncio
import importlib
import logging
from typing import TYPE_CHECKING

from core.models import Order
from core.sources import SOURCES, Source

if TYPE_CHECKING:
    from bot.alerts import Alerter
    from config import Settings
    from parsers.base import BaseParser

log = logging.getLogger(__name__)


def load_factory(path: str):
    """Импортирует фабрику по строке ``"пакет.модуль:функция"``."""
    module_name, _, attr = path.partition(":")
    if not module_name or not attr:
        raise ValueError(f"Некорректный путь фабрики: {path!r}")
    module = importlib.import_module(module_name)
    try:
        return getattr(module, attr)
    except AttributeError as exc:
        raise ValueError(f"В {module_name} нет фабрики {attr!r}") from exc


def build_parsers(
    queue: "asyncio.Queue[Order]",
    settings: "Settings",
    alerter: "Alerter | None" = None,
    *,
    enabled_sources: tuple[str, ...] = (),
) -> list["BaseParser"]:
    """Создаёт парсеры для всех включённых источников с фабриками.

    Args:
        enabled_sources: Ограничение из ``settings.yaml``. Пустой кортеж = все.
    """
    parsers: list[BaseParser] = []
    for source in SOURCES:
        if not source.available or not source.factory:
            continue
        if enabled_sources and source.id not in enabled_sources:
            log.info("Источник '%s' выключен в settings.yaml — пропускаем", source.id)
            continue

        parser = _build_one(source, queue, settings, alerter)
        if parser is not None:
            parsers.append(parser)

    if not parsers:
        log.warning("Ни один источник лидов не запущен — проверьте настройки")
    else:
        log.info("Источники лидов: %s", ", ".join(p.name for p in parsers))
    return parsers


def _build_one(
    source: Source,
    queue: "asyncio.Queue[Order]",
    settings: "Settings",
    alerter: "Alerter | None",
) -> "BaseParser | None":
    try:
        factory = load_factory(source.factory)
    except (ImportError, ValueError) as exc:
        # Обычно это отсутствующая зависимость источника — остальные должны жить.
        log.warning("Источник '%s' недоступен: %s", source.id, exc)
        return None

    try:
        return factory(queue, settings, alerter, source)
    except Exception:  # noqa: BLE001 — кривая фабрика не должна ронять запуск
        log.exception("Источник '%s': фабрика упала", source.id)
        return None

"""Единая настройка логирования для всего приложения."""

from __future__ import annotations

import logging
import sys

_NOISY_LOGGERS = ("telethon", "aiosqlite", "httpx", "httpcore", "hpack", "asyncio")


def setup_logging(level: str = "INFO") -> None:
    """Конфигурирует корневой логгер и приглушает болтливые библиотеки."""
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s | %(levelname)-8s | %(name)-22s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        stream=sys.stdout,
    )
    for name in _NOISY_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)

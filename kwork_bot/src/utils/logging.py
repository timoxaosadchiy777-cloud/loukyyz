"""Единая настройка логирования: консоль + файл с ротацией."""

from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

_NOISY_LOGGERS = (
    "httpx", "httpcore", "hpack", "aiosqlite", "asyncio",
    "google_genai", "google.genai", "aiogram.event", "sqlalchemy.engine",
)

_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)-26s | %(message)s"
_DATEFMT = "%Y-%m-%d %H:%M:%S"


def setup_logging(level: str = "INFO", log_dir: Path | None = None) -> None:
    """Конфигурирует корневой логгер (идемпотентно) и приглушает болтливые библиотеки."""
    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    # Убираем прежние хендлеры, чтобы повторный вызов не дублировал вывод.
    for handler in list(root.handlers):
        root.removeHandler(handler)

    formatter = logging.Formatter(_FORMAT, _DATEFMT)

    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(formatter)
    root.addHandler(console)

    if log_dir is not None:
        log_dir.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(
            log_dir / "kwork_bot.log",
            maxBytes=5_000_000,
            backupCount=5,
            encoding="utf-8",
        )
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)

    for name in _NOISY_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)

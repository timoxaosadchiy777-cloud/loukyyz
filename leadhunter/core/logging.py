"""Единая настройка логирования для всего приложения."""

from __future__ import annotations

import logging
import sys

_NOISY_LOGGERS = ("aiosqlite", "httpx", "httpcore", "hpack", "asyncio")


def _force_utf8_console() -> None:
    """Переводит консоль на UTF-8, чтобы русский текст в логах не падал на Windows.

    В Windows CMD консоль по умолчанию в cp866/cp1251/ascii, и лог-строки с
    кириллицей/эмодзи роняют процесс на UnicodeEncodeError. errors="replace"
    гарантирует, что вывод не сломается даже на неведомой кодировке.
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except (ValueError, OSError):
                pass


def setup_logging(level: str = "INFO") -> None:
    """Конфигурирует корневой логгер и приглушает болтливые библиотеки."""
    _force_utf8_console()
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s | %(levelname)-8s | %(name)-22s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        stream=sys.stdout,
    )
    for name in _NOISY_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)

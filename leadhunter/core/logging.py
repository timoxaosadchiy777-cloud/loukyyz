"""Единая настройка логирования для всего приложения."""

from __future__ import annotations

import logging
import logging.handlers
import sys
from pathlib import Path

_NOISY_LOGGERS = ("aiosqlite", "httpx", "httpcore", "hpack", "asyncio")

_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)-22s | %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


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


def setup_logging(
    level: str = "INFO",
    *,
    log_file: str | Path | None = None,
    max_bytes: int = 10 * 1024 * 1024,
    backups: int = 5,
) -> None:
    """Конфигурирует корневой логгер и приглушает болтливые библиотеки.

    В stdout пишем всегда — так логи видны в ``docker logs`` и journald.
    Если задан ``log_file``, дополнительно включается ротация: файл режется по
    ``max_bytes`` и хранится ``backups`` копий, поэтому лог не съест диск VPS.
    """
    _force_utf8_console()

    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))
    # Пересоздаём хендлеры: повторный вызов (тесты, перезапуск) не должен
    # множить вывод одной строки.
    for handler in list(root.handlers):
        root.removeHandler(handler)
        handler.close()

    formatter = logging.Formatter(_FORMAT, datefmt=_DATE_FORMAT)

    console = logging.StreamHandler(stream=sys.stdout)
    console.setFormatter(formatter)
    root.addHandler(console)

    if log_file:
        try:
            path = Path(log_file)
            path.parent.mkdir(parents=True, exist_ok=True)
            file_handler = logging.handlers.RotatingFileHandler(
                path, maxBytes=max_bytes, backupCount=backups, encoding="utf-8"
            )
            file_handler.setFormatter(formatter)
            root.addHandler(file_handler)
        except OSError as exc:
            # Нет прав на каталог логов — это не повод не запускаться.
            logging.getLogger(__name__).warning(
                "Логи в файл %s недоступны: %s — пишу только в stdout", log_file, exc
            )

    for name in _NOISY_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)

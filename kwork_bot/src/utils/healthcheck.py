"""Healthcheck на файле-heartbeat.

Приложение периодически вызывает `Healthcheck.beat()`. Docker HEALTHCHECK
запускает `python -m utils.healthcheck`, который проверяет свежесть файла и
завершается кодом 0 (жив) или 1 (протух/нет файла).
"""

from __future__ import annotations

import sys
import time
from datetime import datetime, timezone
from pathlib import Path


class Healthcheck:
    """Пишет и проверяет метку живости приложения."""

    def __init__(self, path: Path, *, max_age: float = 300.0) -> None:
        self._path = Path(path)
        self._max_age = max_age

    def beat(self) -> None:
        """Обновляет heartbeat-файл текущим временем."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(datetime.now(timezone.utc).isoformat(), encoding="utf-8")

    def is_alive(self) -> bool:
        """True, если heartbeat-файл существует и свежее `max_age` секунд."""
        try:
            age = time.time() - self._path.stat().st_mtime
        except OSError:
            return False
        return age <= self._max_age


def _main() -> int:
    # Ленивая загрузка настроек — модуль остаётся пригодным как CLI.
    from config.settings import get_settings

    settings = get_settings()
    healthcheck = Healthcheck(settings.healthcheck_file, max_age=settings.kwork_poll_interval * 3 + 60)
    return 0 if healthcheck.is_alive() else 1


if __name__ == "__main__":
    sys.exit(_main())

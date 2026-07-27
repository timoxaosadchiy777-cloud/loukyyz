"""Сигнал живости процесса для healthcheck.

Бот — не HTTP-сервер, поэтому «жив ли он» проверяется не портом, а свежестью
файла-биения. Фоновая задача обновляет его раз в ``interval`` секунд; если
event loop встал (дедлок, зависший await, исчерпанный пул соединений), файл
перестаёт обновляться, healthcheck это видит и Docker перезапускает контейнер.

Проверка именно на зависание: упавший процесс перезапустит и обычная
restart-политика, а вот молча живущий, но ничего не делающий — нет.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from pathlib import Path

log = logging.getLogger(__name__)

# Во сколько раз файл может «состариться», прежде чем считать процесс мёртвым.
STALE_FACTOR = 3


class Heartbeat:
    """Периодически обновляет файл-маркер живости."""

    def __init__(self, path: str | Path, interval: int = 30) -> None:
        self._path = Path(path)
        self._interval = max(5, interval)

    @property
    def path(self) -> Path:
        return self._path

    @property
    def interval(self) -> int:
        return self._interval

    def beat(self) -> None:
        """Обновляет отметку времени. Сбой записи не должен ронять процесс."""
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            # Пишем через временный файл: healthcheck никогда не увидит пустышку.
            tmp = self._path.with_suffix(".tmp")
            tmp.write_text(str(int(time.time())), encoding="utf-8")
            os.replace(tmp, self._path)
        except OSError as exc:
            log.warning("Не удалось обновить heartbeat %s: %s", self._path, exc)

    async def run(self) -> None:
        """Фоновая задача: бьётся, пока жив event loop."""
        log.info("Heartbeat: %s каждые %s c", self._path, self._interval)
        while True:
            self.beat()
            await asyncio.sleep(self._interval)


def is_alive(path: str | Path, interval: int = 30) -> tuple[bool, str]:
    """Проверяет свежесть файла-биения.

    Returns:
        ``(жив, причина)`` — причина заполняется только при отрицательном ответе.
    """
    file = Path(path)
    try:
        raw = file.read_text(encoding="utf-8").strip()
        stamp = int(raw)
    except FileNotFoundError:
        return False, f"нет файла {file} — процесс ещё не стартовал или упал"
    except (OSError, ValueError) as exc:
        return False, f"не читается {file}: {exc}"

    age = int(time.time()) - stamp
    limit = max(5, interval) * STALE_FACTOR
    if age > limit:
        return False, f"нет сигнала {age} c (порог {limit} c) — процесс завис"
    return True, ""

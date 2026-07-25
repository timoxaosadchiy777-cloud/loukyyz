"""Асинхронный ограничитель частоты запросов (минимальный интервал между вызовами)."""

from __future__ import annotations

import asyncio


class RateLimiter:
    """Ограничивает вызовы до `rps` запросов в секунду (равномерный интервал).

    Потокобезопасен для asyncio: сериализует ожидание через `asyncio.Lock`.
    `rps <= 0` отключает ограничение.
    """

    def __init__(self, rps: float) -> None:
        self._min_interval = 1.0 / rps if rps > 0 else 0.0
        self._lock = asyncio.Lock()
        self._last_ts = 0.0

    async def acquire(self) -> None:
        if self._min_interval <= 0:
            return
        async with self._lock:
            loop = asyncio.get_running_loop()
            now = loop.time()
            wait = self._last_ts + self._min_interval - now
            if wait > 0:
                await asyncio.sleep(wait)
            self._last_ts = asyncio.get_running_loop().time()

"""Универсальный асинхронный ретрай с экспоненциальным бэкоффом.

Ретраит только исключения, прошедшие предикат `retry_if` (временные сбои);
остальные пробрасывает сразу. `delay_for` позволяет вычислить задержку из самого
исключения (например, из Retry-After) вместо стандартного бэкоффа.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import TypeVar

log = logging.getLogger(__name__)

T = TypeVar("T")


async def retry_async(
    factory: Callable[[], Awaitable[T]],
    *,
    attempts: int = 4,
    base_delay: float = 2.0,
    max_delay: float = 30.0,
    exceptions: tuple[type[BaseException], ...] = (Exception,),
    retry_if: Callable[[BaseException], bool] | None = None,
    delay_for: Callable[[BaseException, int], float | None] | None = None,
    label: str = "op",
) -> T:
    """Выполняет ``factory()`` с повторами при временных ошибках.

    Args:
        factory: Фабрика корутины — вызывается заново на каждой попытке.
        attempts: Максимум попыток (>= 1).
        base_delay: Базовая задержка бэкоффа, сек.
        max_delay: Верхняя граница задержки, сек.
        exceptions: Классы исключений, которые вообще рассматриваются к ретраю.
        retry_if: Предикат: вернуть ``False`` — исключение пробрасывается сразу.
        delay_for: Функция ``(exc, attempt) -> delay|None``; ``None`` → бэкофф.
        label: Метка для логов.

    Returns:
        Результат успешного вызова ``factory()``.

    Raises:
        Последнее исключение, если попытки исчерпаны или сработал `retry_if=False`.
    """
    attempts = max(1, attempts)
    last_exc: BaseException | None = None

    for attempt in range(1, attempts + 1):
        try:
            return await factory()
        except exceptions as exc:
            if retry_if is not None and not retry_if(exc):
                raise
            last_exc = exc
            if attempt >= attempts:
                break

            delay: float | None = None
            if delay_for is not None:
                delay = delay_for(exc, attempt)
            if delay is None:
                delay = min(base_delay * 2 ** (attempt - 1), max_delay)

            log.warning(
                "[%s] попытка %s/%s не удалась: %s — повтор через %.1f c",
                label, attempt, attempts, exc, delay,
            )
            await asyncio.sleep(delay)

    assert last_exc is not None
    raise last_exc

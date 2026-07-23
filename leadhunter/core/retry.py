"""Универсальный асинхронный ретрай с экспоненциальной задержкой."""

from __future__ import annotations

import asyncio
import logging
from typing import Awaitable, Callable, TypeVar

log = logging.getLogger(__name__)

T = TypeVar("T")


async def retry_async(
    factory: Callable[[], Awaitable[T]],
    *,
    attempts: int = 3,
    base_delay: float = 2.0,
    max_delay: float = 30.0,
    exceptions: tuple[type[BaseException], ...] = (Exception,),
    label: str = "op",
) -> T:
    """Выполняет ``factory()`` с повторами при перечисленных исключениях.

    Задержка растёт экспоненциально: ``base_delay * 2**(attempt-1)`` (до ``max_delay``).
    Исключения вне ``exceptions`` пробрасываются сразу (не ретраятся).

    Args:
        factory: Фабрика корутины — вызывается заново на каждой попытке.
        attempts: Максимум попыток (>= 1).
        base_delay: Базовая задержка в секундах.
        max_delay: Верхняя граница задержки.
        exceptions: Кортеж retryable-исключений.
        label: Метка для логов.

    Returns:
        Результат успешного вызова ``factory()``.

    Raises:
        Последнее пойманное исключение, если все попытки исчерпаны.
    """
    attempts = max(1, attempts)
    last_exc: BaseException | None = None

    for attempt in range(1, attempts + 1):
        try:
            return await factory()
        except exceptions as exc:
            last_exc = exc
            if attempt >= attempts:
                break
            delay = min(base_delay * 2 ** (attempt - 1), max_delay)
            log.warning(
                "[%s] попытка %s/%s не удалась: %s — повтор через %.1f c",
                label,
                attempt,
                attempts,
                exc,
                delay,
            )
            await asyncio.sleep(delay)

    assert last_exc is not None  # достижимо только после ≥1 пойманного исключения
    raise last_exc

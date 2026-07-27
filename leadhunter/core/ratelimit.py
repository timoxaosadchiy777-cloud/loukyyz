"""Ограничение частоты дорогих действий по пользователям.

Нужен там, где кнопка стоит денег: перегенерация отклика — это запрос к
модели, и без ограничения один скучающий пользователь способен выжечь квоту
провайдера на всех остальных. Для локального Ollama эффект тот же: очередь
занята, у остальных лиды не обрабатываются.

Окно скользящее и живёт в памяти: ограничение косметическое по природе (защита
от кликанья, а не от атаки), переживать перезапуск ему не нужно, а лишняя
таблица в базе — лишняя запись на каждое нажатие.
"""

from __future__ import annotations

import time
from collections import OrderedDict, deque

# Сколько пользователей помним. Записи вытесняются по LRU, поэтому словарь не
# растёт бесконечно на боте с большой аудиторией.
MAX_TRACKED_USERS = 10_000


class RateLimiter:
    """Скользящее окно: не больше ``limit`` действий за ``window`` секунд."""

    def __init__(self, limit: int, window: float) -> None:
        self._limit = max(1, limit)
        self._window = max(1.0, window)
        self._hits: OrderedDict[int, deque[float]] = OrderedDict()

    @property
    def limit(self) -> int:
        return self._limit

    @property
    def window(self) -> float:
        return self._window

    def check(self, user_id: int) -> float:
        """Сколько секунд ждать. ``0`` — можно действовать прямо сейчас.

        Успешная проверка сразу засчитывает попытку: разделять «спросить» и
        «отметить» здесь незачем, а так вызывающий код не может забыть отметить.
        """
        now = time.monotonic()
        hits = self._hits.get(user_id)
        if hits is None:
            hits = deque()
            self._hits[user_id] = hits

        self._hits.move_to_end(user_id)
        while len(self._hits) > MAX_TRACKED_USERS:
            self._hits.popitem(last=False)

        # Выкидываем всё, что вышло за окно.
        edge = now - self._window
        while hits and hits[0] <= edge:
            hits.popleft()

        if len(hits) >= self._limit:
            return max(0.0, hits[0] + self._window - now)

        hits.append(now)
        return 0.0

    def reset(self, user_id: int) -> None:
        self._hits.pop(user_id, None)

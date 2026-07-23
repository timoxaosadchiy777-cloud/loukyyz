"""Асинхронное хранилище заказов на aiosqlite.

Отвечает за дедупликацию (UNIQUE по source+external_id), сохранение истории
и статусов (new / accepted / skipped / filtered).
"""

from __future__ import annotations

import logging

import aiosqlite

from core.models import Order

log = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS orders (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    source        TEXT    NOT NULL,
    external_id   TEXT    NOT NULL,
    title         TEXT    NOT NULL,
    url           TEXT    NOT NULL,
    description   TEXT    NOT NULL,
    budget_raw    TEXT,
    budget_value  INTEGER,
    response      TEXT,
    status        TEXT    NOT NULL DEFAULT 'new',
    created_at    TEXT    NOT NULL,
    UNIQUE(source, external_id)
);

CREATE INDEX IF NOT EXISTS idx_orders_source_ext ON orders(source, external_id);
CREATE INDEX IF NOT EXISTS idx_orders_status     ON orders(status);
"""


class Database:
    """Тонкая обёртка над одним соединением aiosqlite."""

    def __init__(self, path: str) -> None:
        self._path = path
        self._conn: aiosqlite.Connection | None = None

    @property
    def _connection(self) -> aiosqlite.Connection:
        if self._conn is None:
            raise RuntimeError("Database.connect() не был вызван")
        return self._conn

    async def connect(self) -> None:
        self._conn = await aiosqlite.connect(self._path)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.executescript(_SCHEMA)
        await self._conn.commit()
        log.info("SQLite подключена: %s", self._path)

    async def close(self) -> None:
        if self._conn is not None:
            await self._conn.close()
            self._conn = None

    async def is_duplicate(self, source: str, external_id: str) -> bool:
        cur = await self._connection.execute(
            "SELECT 1 FROM orders WHERE source = ? AND external_id = ? LIMIT 1",
            (source, external_id),
        )
        return await cur.fetchone() is not None

    async def save_order(
        self,
        order: Order,
        response: str = "",
        status: str = "new",
    ) -> int | None:
        """Сохраняет заказ. Возвращает id новой записи или ``None`` для дубликата."""
        cur = await self._connection.execute(
            """
            INSERT OR IGNORE INTO orders
                (source, external_id, title, url, description,
                 budget_raw, budget_value, response, status, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                order.source,
                order.external_id,
                order.title,
                order.url,
                order.description,
                order.budget_raw,
                order.budget_value,
                response,
                status,
                order.created_at.isoformat(),
            ),
        )
        await self._connection.commit()
        # rowcount == 0 → сработал OR IGNORE (дубликат проскочил гонку).
        return cur.lastrowid if cur.rowcount else None

    async def get_order(self, order_id: int) -> aiosqlite.Row | None:
        cur = await self._connection.execute(
            "SELECT * FROM orders WHERE id = ?", (order_id,)
        )
        return await cur.fetchone()

    async def set_status(self, order_id: int, status: str) -> None:
        await self._connection.execute(
            "UPDATE orders SET status = ? WHERE id = ?", (status, order_id)
        )
        await self._connection.commit()

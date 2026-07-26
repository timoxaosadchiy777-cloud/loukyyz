"""Тесты хранилища: сохранение оценки, CRM-статус, from_row, миграция схемы."""

from __future__ import annotations

import aiosqlite
import pytest_asyncio

from core.models import CrmStatus, Order
from database.db import Database


@pytest_asyncio.fixture
async def db(tmp_path):
    database = Database(str(tmp_path / "test.db"))
    await database.connect()
    try:
        yield database
    finally:
        await database.close()


def _scored_order() -> Order:
    return Order(
        source="rss",
        external_id="ext-1",
        title="Нужен Telegram бот",
        url="https://example.com/1",
        description="Бот приёма заявок",
        budget_raw="$300",
        budget_value=300,
        score=93,
        category="Telegram Bot",
        reason="полностью по профилю",
        probability_of_sale=72,
        should_send=True,
    )


async def test_save_and_read_roundtrip(db) -> None:
    order_id = await db.save_order(_scored_order(), response="proposal", status="new")
    assert order_id is not None

    row = await db.get_order(order_id)
    assert row["score"] == 93
    assert row["category"] == "Telegram Bot"
    assert row["reason"] == "полностью по профилю"
    assert row["probability_of_sale"] == 72
    assert row["should_send"] == 1
    assert row["crm_status"] == CrmStatus.NEW
    assert row["response"] == "proposal"

    restored = Order.from_row(row)
    assert restored.score == 93
    assert restored.category == "Telegram Bot"
    assert restored.probability_of_sale == 72
    assert restored.should_send is True
    assert restored.crm_status == CrmStatus.NEW


async def test_duplicate_ignored(db) -> None:
    first = await db.save_order(_scored_order())
    second = await db.save_order(_scored_order())
    assert first is not None
    assert second is None  # UNIQUE(source, external_id) → OR IGNORE
    assert await db.is_duplicate("rss", "ext-1") is True


async def test_set_crm_status(db) -> None:
    order_id = await db.save_order(_scored_order())
    await db.set_crm_status(order_id, CrmStatus.NEGOTIATION)
    row = await db.get_order(order_id)
    assert row["crm_status"] == CrmStatus.NEGOTIATION


async def test_unknown_score_persists_as_null(db) -> None:
    order = Order(source="rss", external_id="x", title="t", url="u", description="d")
    order_id = await db.save_order(order, response="", status="new")
    row = await db.get_order(order_id)
    assert row["score"] is None
    assert row["should_send"] is None
    assert Order.from_row(row).should_send is None


async def test_migration_adds_columns_to_legacy_db(tmp_path) -> None:
    """Старая БД без AI/CRM-колонок должна мигрировать без потери данных."""
    path = tmp_path / "legacy.db"
    async with aiosqlite.connect(str(path)) as conn:
        await conn.execute(
            """
            CREATE TABLE orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source TEXT NOT NULL,
                external_id TEXT NOT NULL,
                title TEXT NOT NULL,
                url TEXT NOT NULL,
                description TEXT NOT NULL,
                budget_raw TEXT,
                budget_value INTEGER,
                response TEXT,
                status TEXT NOT NULL DEFAULT 'new',
                created_at TEXT NOT NULL,
                UNIQUE(source, external_id)
            )
            """
        )
        await conn.execute(
            "INSERT INTO orders (source, external_id, title, url, description, status, created_at)"
            " VALUES ('rss','old','t','u','d','new','2020-01-01T00:00:00+00:00')"
        )
        await conn.commit()

    database = Database(str(path))
    await database.connect()  # запускает миграцию
    try:
        # Новые колонки появились; старая запись цела и получила дефолты.
        cur = await database._connection.execute("PRAGMA table_info(orders)")
        cols = {r["name"] for r in await cur.fetchall()}
        assert {
            "score", "category", "reason", "probability_of_sale", "should_send", "crm_status"
        } <= cols

        cur = await database._connection.execute(
            "SELECT crm_status, score FROM orders WHERE external_id='old'"
        )
        legacy = await cur.fetchone()
        assert legacy["crm_status"] == "new"
        assert legacy["score"] is None

        # И новые заказы сохраняются в мигрированную таблицу.
        new_id = await database.save_order(_scored_order())
        assert new_id is not None
    finally:
        await database.close()

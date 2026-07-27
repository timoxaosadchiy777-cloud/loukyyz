"""Тесты мультипользовательского слоя: таблица users и выдача доступа."""

from __future__ import annotations

import aiosqlite
import pytest_asyncio

from database.db import Database


@pytest_asyncio.fixture
async def db(tmp_path):
    database = Database(str(tmp_path / "users.db"))
    await database.connect()
    try:
        yield database
    finally:
        await database.close()


async def test_users_table_created(db) -> None:
    cur = await db._connection.execute("PRAGMA table_info(users)")
    cols = {r["name"] for r in await cur.fetchall()}
    assert cols == {
        "telegram_id",
        "username",
        "paid_status",
        "created_at",
        "access_requested_at",
    }


async def test_new_user_has_no_access(db) -> None:
    await db.register_user(111, "vasya")
    assert await db.has_paid_access(111) is False
    row = await db.get_user(111)
    assert row["username"] == "vasya"
    assert row["paid_status"] == 0
    assert row["created_at"]


async def test_unknown_user_has_no_access(db) -> None:
    assert await db.has_paid_access(999) is False
    assert await db.get_user(999) is None


async def test_grant_and_revoke(db) -> None:
    await db.register_user(111, "vasya")

    await db.set_paid_status(111, True)
    assert await db.has_paid_access(111) is True

    await db.set_paid_status(111, False)
    assert await db.has_paid_access(111) is False


async def test_grant_creates_user_that_never_started_bot(db) -> None:
    """Доступ можно выдать заранее — по одному telegram_id, без /start."""
    await db.set_paid_status(222, True)
    assert await db.has_paid_access(222) is True
    assert (await db.get_user(222))["paid_status"] == 1


async def test_register_does_not_reset_access(db) -> None:
    """Повторный /start у оплаченного пользователя не отбирает доступ."""
    await db.set_paid_status(111, True, username="vasya")
    await db.register_user(111, "vasya_renamed")

    assert await db.has_paid_access(111) is True
    assert (await db.get_user(111))["username"] == "vasya_renamed"


async def test_list_users_puts_paid_first(db) -> None:
    await db.register_user(1, "free")
    await db.register_user(2, "paid")
    await db.set_paid_status(2, True)

    rows = await db.list_users()
    assert [r["telegram_id"] for r in rows] == [2, 1]

    assert await db.count_users() == (2, 1)


async def test_count_users_on_empty_table(db) -> None:
    assert await db.count_users() == (0, 0)


async def test_users_table_appears_on_legacy_db(tmp_path) -> None:
    """Старая БД (только orders) получает users без потери заказов."""
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
    await database.connect()
    try:
        await database.set_paid_status(111, True)
        assert await database.has_paid_access(111) is True

        # Старый заказ на месте.
        cur = await database._connection.execute(
            "SELECT COUNT(*) AS n FROM orders WHERE external_id = 'old'"
        )
        assert (await cur.fetchone())["n"] == 1
    finally:
        await database.close()

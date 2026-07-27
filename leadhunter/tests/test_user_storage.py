"""Тесты хранения персональных фильтров и избранных лидов."""

from __future__ import annotations

import aiosqlite
import pytest_asyncio

from core.models import Order
from core.user_settings import UserSettings
from database.db import Database

USER = 111
OTHER = 222


@pytest_asyncio.fixture
async def db(tmp_path):
    database = Database(str(tmp_path / "storage.db"))
    await database.connect()
    try:
        yield database
    finally:
        await database.close()


def _order(external_id: str = "1", **kwargs) -> Order:
    base = dict(
        source="freelancer",
        external_id=external_id,
        title="Telegram бот",
        url="https://example.com",
        description="Парсинг и выгрузка",
    )
    base.update(kwargs)
    return Order(**base)


# --- Персональные фильтры -------------------------------------------------


async def test_unknown_user_gets_defaults(db) -> None:
    from core.sources import default_enabled_ids

    settings = await db.get_user_settings(USER)
    assert settings.onboarded is False
    assert settings.categories == ()
    assert settings.keywords == ()
    # Источники приходят из реестра: включено то, что default_enabled.
    assert settings.sources == default_enabled_ids()


async def test_settings_roundtrip(db) -> None:
    settings = UserSettings(
        sources=("rss", "upwork"),
        categories=("Telegram-боты", "AI и LLM"),
        keywords=("python", "парсинг"),
        min_budget=300,
        onboarded=True,
    )
    await db.save_user_settings(USER, settings)
    stored = await db.get_user_settings(USER)
    # Источники живут в отдельной таблице, поэтому сравниваем остальное.
    assert stored.categories == settings.categories
    assert stored.keywords == settings.keywords
    assert stored.min_budget == settings.min_budget
    assert stored.onboarded is True


async def test_settings_are_per_user(db) -> None:
    """Фильтры одного пользователя не видны другому."""
    await db.save_user_settings(USER, UserSettings(min_budget=500, onboarded=True))
    assert (await db.get_user_settings(OTHER)).min_budget == 0
    assert (await db.get_user_settings(OTHER)).onboarded is False


async def test_settings_overwrite(db) -> None:
    await db.save_user_settings(USER, UserSettings(keywords=("python",)))
    await db.save_user_settings(USER, UserSettings(keywords=("go",), min_budget=100))
    settings = await db.get_user_settings(USER)
    assert settings.keywords == ("go",)
    assert settings.min_budget == 100


async def test_empty_lists_roundtrip_as_empty(db) -> None:
    """Пустой список не должен превратиться в ('',) — иначе фильтр сломается."""
    await db.save_user_settings(USER, UserSettings(onboarded=True))
    settings = await db.get_user_settings(USER)
    assert settings.categories == ()
    assert settings.keywords == ()


# --- Избранные лиды -------------------------------------------------------


async def test_save_and_list_lead(db) -> None:
    order_id = await db.save_order(_order())
    await db.save_lead(USER, order_id)

    assert await db.is_lead_saved(USER, order_id) is True
    rows = await db.list_saved_leads(USER)
    assert [r["id"] for r in rows] == [order_id]
    assert rows[0]["title"] == "Telegram бот"


async def test_saved_leads_are_per_user(db) -> None:
    order_id = await db.save_order(_order())
    await db.save_lead(USER, order_id)

    assert await db.is_lead_saved(OTHER, order_id) is False
    assert await db.list_saved_leads(OTHER) == []


async def test_save_lead_is_idempotent(db) -> None:
    order_id = await db.save_order(_order())
    await db.save_lead(USER, order_id)
    await db.save_lead(USER, order_id)
    assert len(await db.list_saved_leads(USER)) == 1


async def test_unsave_lead(db) -> None:
    order_id = await db.save_order(_order())
    await db.save_lead(USER, order_id)
    await db.unsave_lead(USER, order_id)

    assert await db.is_lead_saved(USER, order_id) is False
    assert await db.list_saved_leads(USER) == []


async def test_unsave_missing_lead_is_noop(db) -> None:
    await db.unsave_lead(USER, 999)
    assert await db.list_saved_leads(USER) == []


# --- Подбор для «Проверить сейчас» ----------------------------------------


async def test_recent_orders_skips_filtered_and_rejected(db) -> None:
    await db.save_order(_order("a"), status="new")
    await db.save_order(_order("b"), status="rejected")
    await db.save_order(_order("c"), status="filtered")

    rows = await db.recent_orders()
    assert [r["external_id"] for r in rows] == ["a"]


async def test_recent_orders_newest_first_and_limited(db) -> None:
    for i in range(5):
        await db.save_order(_order(str(i)), status="new")

    rows = await db.recent_orders(limit=3)
    assert [r["external_id"] for r in rows] == ["4", "3", "2"]


async def test_recent_orders_feed_user_filter(db) -> None:
    """Связка «свежие лиды → персональный фильтр» — основа «Проверить сейчас»."""
    await db.save_order(_order("wp", title="Сайт на WordPress"), status="new")
    await db.save_order(_order("tg", title="Telegram бот на Python"), status="new")

    settings = UserSettings(keywords=("telegram",))
    matched = [r for r in await db.recent_orders() if settings.matches(Order.from_row(r))]
    assert [r["external_id"] for r in matched] == ["tg"]


# --- Совместимость со старой базой ----------------------------------------


async def test_new_tables_appear_on_legacy_db(tmp_path) -> None:
    path = tmp_path / "legacy.db"
    async with aiosqlite.connect(str(path)) as conn:
        await conn.execute(
            """
            CREATE TABLE orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source TEXT NOT NULL, external_id TEXT NOT NULL,
                title TEXT NOT NULL, url TEXT NOT NULL, description TEXT NOT NULL,
                budget_raw TEXT, budget_value INTEGER, response TEXT,
                status TEXT NOT NULL DEFAULT 'new', created_at TEXT NOT NULL,
                UNIQUE(source, external_id)
            )
            """
        )
        await conn.commit()

    database = Database(str(path))
    await database.connect()
    try:
        await database.save_user_settings(USER, UserSettings(onboarded=True))
        assert (await database.get_user_settings(USER)).onboarded is True

        order_id = await database.save_order(_order())
        await database.save_lead(USER, order_id)
        assert len(await database.list_saved_leads(USER)) == 1
    finally:
        await database.close()


async def test_saved_leads_migrate_into_deliveries(tmp_path) -> None:
    """Избранное из версии 2.x не должно потеряться при переезде в доставки."""
    path = tmp_path / "v2.db"

    database = Database(str(path))
    await database.connect()
    order_id = await database.save_order(_order("kept"))
    await database.close()

    # Воспроизводим состояние 2.x: избранное лежит в отдельной таблице.
    async with aiosqlite.connect(str(path)) as conn:
        await conn.execute("DROP TABLE lead_deliveries")
        await conn.execute(
            "CREATE TABLE saved_leads (telegram_id INTEGER NOT NULL,"
            " order_id INTEGER NOT NULL, created_at TEXT NOT NULL,"
            " PRIMARY KEY (telegram_id, order_id))"
        )
        await conn.execute(
            "INSERT INTO saved_leads VALUES (?, ?, '2024-01-01T00:00:00+00:00')",
            (USER, order_id),
        )
        await conn.commit()

    database = Database(str(path))
    await database.connect()  # запускает миграцию
    try:
        assert await database.is_lead_saved(USER, order_id) is True
        assert [r["id"] for r in await database.list_saved_leads(USER)] == [order_id]
    finally:
        await database.close()


async def test_migration_is_idempotent(tmp_path) -> None:
    path = tmp_path / "twice.db"
    database = Database(str(path))
    await database.connect()
    order_id = await database.save_order(_order("x"))
    await database.save_lead(USER, order_id)
    await database.close()

    for _ in range(2):
        database = Database(str(path))
        await database.connect()
        assert len(await database.list_saved_leads(USER)) == 1
        await database.close()

"""Тесты проверки доступа: админ, оплаченный пользователь, dev-режим."""

from __future__ import annotations

import pytest_asyncio

from bot.access import AccessControl
from database.db import Database

OWNER = 100
STRANGER = 200
PAID = 300


@pytest_asyncio.fixture
async def db(tmp_path):
    database = Database(str(tmp_path / "access.db"))
    await database.connect()
    try:
        yield database
    finally:
        await database.close()


async def test_admin_has_access_without_db_record(db) -> None:
    """Владелец не хранится в users — доступ у него безусловный."""
    access = AccessControl(db, owner_id=OWNER)
    assert access.is_admin(OWNER) is True
    assert await access.has_access(OWNER) is True
    assert await db.get_user(OWNER) is None


async def test_stranger_has_no_access(db) -> None:
    access = AccessControl(db, owner_id=OWNER)
    assert access.is_admin(STRANGER) is False
    assert await access.has_access(STRANGER) is False


async def test_registered_but_unpaid_has_no_access(db) -> None:
    access = AccessControl(db, owner_id=OWNER)
    await db.register_user(STRANGER, "vasya")
    assert await access.has_access(STRANGER) is False


async def test_paid_user_has_access_but_is_not_admin(db) -> None:
    access = AccessControl(db, owner_id=OWNER)
    await db.set_paid_status(PAID, True)
    assert await access.has_access(PAID) is True
    assert access.is_admin(PAID) is False


async def test_access_lost_after_revoke(db) -> None:
    access = AccessControl(db, owner_id=OWNER)
    await db.set_paid_status(PAID, True)
    await db.set_paid_status(PAID, False)
    assert await access.has_access(PAID) is False


async def test_admin_keeps_access_after_self_revoke_attempt(db) -> None:
    """Даже если в users владельцу проставили 0 — доступ остаётся."""
    access = AccessControl(db, owner_id=OWNER)
    await db.set_paid_status(OWNER, False)
    assert await access.has_access(OWNER) is True


async def test_dev_mode_allows_everyone(db) -> None:
    """OWNER_ID не задан — поведение как до мультиюзера: пускаем всех."""
    access = AccessControl(db, owner_id=0)
    assert access.dev_mode is True
    assert access.is_admin(STRANGER) is True
    assert await access.has_access(STRANGER) is True


async def test_anonymous_user_denied(db) -> None:
    access = AccessControl(db, owner_id=OWNER)
    assert access.is_admin(None) is False
    assert await access.has_access(None) is False

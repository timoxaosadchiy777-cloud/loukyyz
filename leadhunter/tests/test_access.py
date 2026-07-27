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


async def test_dev_mode_must_be_explicit(db) -> None:
    """Забытый OWNER_ID не должен открывать бота и админку посторонним."""
    access = AccessControl(db, owner_id=0)
    assert access.dev_mode is False
    assert access.configured is False
    assert access.is_admin(STRANGER) is False
    assert await access.has_access(STRANGER) is False


async def test_dev_mode_opens_access_but_not_admin(db) -> None:
    """DEV_MODE — для локальной отладки: пускает всех, но админом не делает."""
    access = AccessControl(db, owner_id=0, dev_mode=True)
    assert await access.has_access(STRANGER) is True
    assert access.is_admin(STRANGER) is False


async def test_anonymous_user_denied(db) -> None:
    access = AccessControl(db, owner_id=OWNER)
    assert access.is_admin(None) is False
    assert await access.has_access(None) is False


async def test_paid_user_cannot_read_foreign_lead(bot_db, access, cq, rec, fsm) -> None:
    """order_id приходит от клиента: перебором нельзя вытащить чужой лид."""
    from bot.bot import on_order_action
    from bot.callbacks import OrderAction
    from core.models import Order
    from tests.helpers import USER

    order_id = await bot_db.save_order(
        Order(source="freelancer", external_id="secret", title="Чужой лид",
              url="u", description="d"),
        response="секретный отклик",
        status="new",
    )
    # USER имеет доступ к боту, но этот лид ему не доставляли.
    await on_order_action(
        cq(USER), OrderAction(action="copy", order_id=order_id), bot_db, access, fsm
    )

    assert not rec.has("секретный отклик")
    assert rec.alerts  # ответили отказом, а не текстом лида


async def test_delivered_lead_is_readable(bot_db, access, cq, rec, fsm) -> None:
    from bot.bot import on_order_action
    from bot.callbacks import OrderAction
    from core.models import Order
    from tests.helpers import USER

    order_id = await bot_db.save_order(
        Order(source="freelancer", external_id="mine", title="Мой лид", url="u", description="d"),
        response="мой отклик",
        status="new",
    )
    await bot_db.mark_delivered(USER, order_id, "мой отклик")

    await on_order_action(
        cq(USER), OrderAction(action="copy", order_id=order_id), bot_db, access, fsm
    )
    assert rec.has("мой отклик")

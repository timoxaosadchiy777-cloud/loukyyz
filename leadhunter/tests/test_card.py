"""Тесты персональной карточки: сохранить, изменить отклик, отклонить, CRM."""

from __future__ import annotations

import pytest

from bot.bot import CardStates, on_crm_action, on_order_action, on_rewrite_text
from bot import texts
from bot.callbacks import CrmAction, OrderAction
from core.models import CrmStatus, LeadState, Order
from tests.helpers import STRANGER, USER, labels

OTHER = 777


def _order(**kwargs) -> Order:
    base = dict(
        source="freelancer",
        external_id="1",
        title="Telegram бот",
        url="https://example.com/1",
        description="Приём заявок",
        score=90,
        category="Telegram-боты",
    )
    base.update(kwargs)
    return Order(**base)


class _Responder:
    def __init__(self, text: str | None = "новый черновик") -> None:
        self.text = text
        self.calls = 0

    async def generate(self, order, analysis=None):
        self.calls += 1
        return self.text


@pytest.fixture
def responder() -> _Responder:
    return _Responder()


async def _make_order(db, response: str = "общий черновик") -> int:
    """Заказ, доставленный USER: право на действия даёт именно факт доставки."""
    order_id = await db.save_order(_order(), response=response, status="new")
    await db.mark_delivered(USER, order_id, response)
    return order_id


# --- Кнопки, которых требует ТЗ -------------------------------------------


async def test_card_has_required_buttons(bot_db, access, cq, rec, fsm) -> None:
    order_id = await _make_order(bot_db)
    await on_order_action(
        cq(), OrderAction(action="save", order_id=order_id), bot_db, access, fsm
    )

    buttons = labels(rec.last_markup)
    assert "✍️ Изменить отклик" in buttons
    assert "❌ Отклонить" in buttons
    assert "💔 Убрать из сохранённых" in buttons  # ❤️ переключилось после сохранения


# --- ❌ Отклонить ---------------------------------------------------------


async def test_reject_marks_state_and_hides_actions(bot_db, access, cq, rec, fsm) -> None:
    order_id = await _make_order(bot_db)
    await on_order_action(
        cq(), OrderAction(action="reject", order_id=order_id), bot_db, access, fsm
    )

    assert (await bot_db.get_delivery(USER, order_id))["state"] == LeadState.REJECTED
    assert rec.has("Отклонён")
    assert labels(rec.last_markup) == []  # кнопок больше нет
    assert "Лид отклонён" in rec.alerts


async def test_reject_is_personal(bot_db, access, cq, fsm) -> None:
    order_id = await _make_order(bot_db)
    await bot_db.mark_delivered(OTHER, order_id, "черновик")

    await on_order_action(
        cq(), OrderAction(action="reject", order_id=order_id), bot_db, access, fsm
    )

    assert (await bot_db.get_delivery(OTHER, order_id))["state"] == LeadState.SENT


# --- ✍️ Изменить отклик ---------------------------------------------------


async def test_rewrite_offers_regenerate_and_manual(bot_db, access, cq, rec, fsm) -> None:
    order_id = await _make_order(bot_db)
    await on_order_action(
        cq(), OrderAction(action="rewrite", order_id=order_id), bot_db, access, fsm
    )

    assert await fsm.get_state() == CardStates.rewrite
    assert rec.has("Свой вариант отклика")
    assert "🔄 Сгенерировать заново" in labels(rec.last_markup)


async def test_manual_rewrite_saves_personal_response(bot_db, access, cq, msg, rec, fsm) -> None:
    order_id = await _make_order(bot_db)
    await bot_db.mark_delivered(USER, order_id, "общий черновик")
    await bot_db.mark_delivered(OTHER, order_id, "общий черновик")

    await on_order_action(
        cq(), OrderAction(action="rewrite", order_id=order_id), bot_db, access, fsm
    )
    await on_rewrite_text(msg(text="мой личный отклик"), bot_db, access, fsm)

    assert (await bot_db.get_delivery(USER, order_id))["response"] == "мой личный отклик"
    # Чужой черновик не тронут.
    assert (await bot_db.get_delivery(OTHER, order_id))["response"] == "общий черновик"
    assert await fsm.get_state() is None
    assert rec.has("Отклик обновлён")


async def test_regenerate_asks_ai_and_stores_result(
    bot_db, access, cq, rec, fsm, responder
) -> None:
    order_id = await _make_order(bot_db)
    await bot_db.mark_delivered(USER, order_id, "общий черновик")

    await on_order_action(
        cq(), OrderAction(action="regen", order_id=order_id), bot_db, access, fsm, responder
    )

    assert responder.calls == 1
    assert (await bot_db.get_delivery(USER, order_id))["response"] == "новый черновик"
    assert rec.has("Новый вариант отклика")


async def test_regenerate_without_responder_is_honest(bot_db, access, cq, rec, fsm) -> None:
    order_id = await _make_order(bot_db)
    await on_order_action(
        cq(), OrderAction(action="regen", order_id=order_id), bot_db, access, fsm, None
    )
    assert texts.ERR_GENERATION_OFF in rec.alerts


async def test_regenerate_survives_ai_failure(bot_db, access, cq, rec, fsm) -> None:
    order_id = await _make_order(bot_db)
    await bot_db.mark_delivered(USER, order_id, "общий черновик")

    await on_order_action(
        cq(),
        OrderAction(action="regen", order_id=order_id),
        bot_db,
        access,
        fsm,
        _Responder(None),
    )

    assert rec.has("ИИ сейчас недоступен")
    # Прежний черновик остался на месте.
    assert (await bot_db.get_delivery(USER, order_id))["response"] == "общий черновик"


async def test_cancel_rewrite_clears_state(bot_db, access, cq, rec, fsm) -> None:
    order_id = await _make_order(bot_db)
    await on_order_action(
        cq(), OrderAction(action="rewrite", order_id=order_id), bot_db, access, fsm
    )
    await on_order_action(
        cq(), OrderAction(action="cancel_rewrite", order_id=order_id), bot_db, access, fsm
    )
    assert await fsm.get_state() is None


# --- 📋 Копирование берёт личный отклик -----------------------------------


async def test_copy_prefers_personal_response(bot_db, access, cq, rec, fsm) -> None:
    order_id = await _make_order(bot_db, response="общий черновик")
    await bot_db.set_delivery_response(USER, order_id, "мой вариант")

    await on_order_action(
        cq(), OrderAction(action="copy", order_id=order_id), bot_db, access, fsm
    )
    assert rec.has("мой вариант")


async def test_copy_falls_back_to_shared_response(bot_db, access, cq, rec, fsm) -> None:
    """У владельца до fan-out доставки нет — берём отклик из заказа."""
    order_id = await _make_order(bot_db, response="общий черновик")

    await on_order_action(
        cq(), OrderAction(action="copy", order_id=order_id), bot_db, access, fsm
    )
    assert rec.has("общий черновик")


# --- CRM теперь персональный ----------------------------------------------


async def test_crm_status_is_personal(bot_db, access, cq, rec) -> None:
    order_id = await _make_order(bot_db)
    await bot_db.mark_delivered(OTHER, order_id, "черновик")

    await on_crm_action(
        cq(), CrmAction(status=CrmStatus.WON, order_id=order_id), bot_db, access
    )

    assert (await bot_db.get_delivery(USER, order_id))["crm_status"] == CrmStatus.WON
    assert (await bot_db.get_delivery(OTHER, order_id))["crm_status"] == CrmStatus.NEW
    # Общий статус заказа не тронут — он остаётся историческим.
    assert (await bot_db.get_order(order_id))["crm_status"] == CrmStatus.NEW


async def test_crm_rejects_unknown_status(bot_db, access, cq, rec) -> None:
    order_id = await _make_order(bot_db)
    await on_crm_action(
        cq(), CrmAction(status="выдумка", order_id=order_id), bot_db, access
    )
    assert texts.ERR_UNKNOWN_STATUS in rec.alerts


async def test_card_shows_personal_crm_after_redraw(bot_db, access, cq, rec) -> None:
    order_id = await _make_order(bot_db)
    await on_crm_action(
        cq(), CrmAction(status=CrmStatus.CONTACTED, order_id=order_id), bot_db, access
    )
    assert "• ✉️ Написал" in labels(rec.last_markup)


# --- Доступ ---------------------------------------------------------------


async def test_all_card_actions_require_access(bot_db, access, cq, rec, fsm) -> None:
    order_id = await _make_order(bot_db)
    for action in ("copy", "save", "reject", "rewrite", "regen"):
        await on_order_action(
            cq(STRANGER), OrderAction(action=action, order_id=order_id), bot_db, access, fsm
        )
    await on_crm_action(
        cq(STRANGER), CrmAction(status=CrmStatus.WON, order_id=order_id), bot_db, access
    )

    assert rec.alerts == [texts.ERR_NO_ACCESS] * 6
    assert await bot_db.get_delivery(STRANGER, order_id) is None


async def test_missing_order_is_reported(bot_db, access, cq, rec, fsm) -> None:
    await on_order_action(
        cq(), OrderAction(action="save", order_id=9999), bot_db, access, fsm
    )
    assert texts.ERR_ORDER_GONE in rec.alerts

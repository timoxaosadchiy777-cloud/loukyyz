"""Тесты коммерческой части: заявки на доступ, админ-панель, справка, ошибки."""

from __future__ import annotations

from aiogram.types import ErrorEvent, Update

from bot import texts
from bot.admin import (
    on_access_decision,
    on_admin_action,
    on_admin_command,
    on_user_toggle,
)
from bot.bot import on_access_request, on_error, on_help, on_help_button, on_start
from bot.callbacks import AccessAction, AdminAction, HelpAction, UserAction
from tests.helpers import OWNER, STRANGER, USER, callback_for, labels

NEWCOMER = 4242


# --- Стартовый экран ------------------------------------------------------


async def test_locked_start_sells_and_offers_one_tap_request(
    msg, bot_db, access, rec, fsm
) -> None:
    await on_start(msg(NEWCOMER), bot_db, access, fsm)

    # Продающая часть, а не сухое «нет доступа».
    assert rec.has("заказы с фриланс-бирж")
    assert rec.has("Готовый отклик")
    assert "📨 Запросить доступ" in labels(rec.last_markup)
    # ID показываем, но копировать его вручную больше не требуется.
    assert rec.has(str(NEWCOMER))


async def test_request_button_carries_the_user(msg, bot_db, access, rec, fsm) -> None:
    await on_start(msg(NEWCOMER), bot_db, access, fsm)
    assert callback_for(rec.last_markup, "Запросить") == AccessAction(
        action="request", user_id=NEWCOMER
    ).pack()


# --- Заявка на доступ -----------------------------------------------------


async def test_request_reaches_admin_with_decision_buttons(
    cq, bot_db, rec, tg_bot
) -> None:
    await on_access_request(
        cq(NEWCOMER), AccessAction(action="request", user_id=NEWCOMER), bot_db, OWNER
    )

    assert rec.has("Заявка отправлена")
    assert tg_bot.chats == [OWNER]
    assert "✅ Выдать доступ" in labels(tg_bot.markup_for(OWNER))
    assert "❌ Отклонить" in labels(tg_bot.markup_for(OWNER))
    assert [r["telegram_id"] for r in await bot_db.list_access_requests()] == [NEWCOMER]


async def test_repeat_request_does_not_spam_admin(cq, bot_db, rec, tg_bot) -> None:
    action = AccessAction(action="request", user_id=NEWCOMER)
    await on_access_request(cq(NEWCOMER), action, bot_db, OWNER)
    await on_access_request(cq(NEWCOMER), action, bot_db, OWNER)

    assert tg_bot.chats == [OWNER]  # ровно одно уведомление
    assert texts.REQUEST_ALREADY_SENT in rec.alerts


async def test_request_survives_missing_owner(cq, bot_db, rec, tg_bot) -> None:
    """OWNER_ID не задан — заявка всё равно сохраняется, бот не падает."""
    await on_access_request(
        cq(NEWCOMER), AccessAction(action="request", user_id=NEWCOMER), bot_db, 0
    )
    assert tg_bot.sent == []
    assert len(await bot_db.list_access_requests()) == 1


# --- Решение администратора ----------------------------------------------


async def test_admin_grants_in_one_tap(cq, bot_db, access, rec, tg_bot) -> None:
    await bot_db.request_access(NEWCOMER, "vasya")

    await on_access_decision(
        cq(OWNER), AccessAction(action="grant", user_id=NEWCOMER), bot_db, access
    )

    assert await access.has_access(NEWCOMER) is True
    assert await bot_db.list_access_requests() == []  # заявка закрыта
    assert texts.ACCESS_GRANTED in tg_bot.to(NEWCOMER)


async def test_admin_declines(cq, bot_db, access, rec, tg_bot) -> None:
    await bot_db.request_access(NEWCOMER, "vasya")

    await on_access_decision(
        cq(OWNER), AccessAction(action="decline", user_id=NEWCOMER), bot_db, access
    )

    assert await access.has_access(NEWCOMER) is False
    assert await bot_db.list_access_requests() == []
    assert texts.ACCESS_DECLINED in tg_bot.to(NEWCOMER)


async def test_stranger_cannot_grant_access(cq, bot_db, access, rec) -> None:
    await bot_db.request_access(NEWCOMER, "vasya")

    await on_access_decision(
        cq(STRANGER), AccessAction(action="grant", user_id=NEWCOMER), bot_db, access
    )

    assert await access.has_access(NEWCOMER) is False
    assert texts.ERR_NO_ACCESS in rec.alerts


async def test_granted_user_can_reach_the_wizard(msg, bot_db, access, rec, fsm) -> None:
    """Сквозной путь: заявка → выдача → мастер настройки."""
    await bot_db.set_paid_status(NEWCOMER, True)
    await on_start(msg(NEWCOMER), bot_db, access, fsm)
    assert rec.has("Шаг 1/4")


# --- Админ-панель ---------------------------------------------------------


async def test_admin_panel_opens_for_owner(msg, bot_db, access, rec) -> None:
    await on_admin_command(msg(OWNER), bot_db, access)

    assert rec.has("Админ-панель")
    assert labels(rec.last_markup) == ["👥 Пользователи", "📨 Заявки", "📊 Статистика"]


async def test_admin_panel_is_silent_for_others(msg, bot_db, access, rec) -> None:
    await on_admin_command(msg(USER), bot_db, access)
    assert rec.texts == []


async def test_pending_requests_are_counted_on_the_button(
    msg, bot_db, access, rec
) -> None:
    await bot_db.request_access(NEWCOMER, "vasya")
    await on_admin_command(msg(OWNER), bot_db, access)
    assert "📨 Заявки (1)" in labels(rec.last_markup)


async def test_users_screen_toggles_access_by_tap(cq, bot_db, access, rec, tg_bot) -> None:
    await bot_db.register_user(NEWCOMER, "vasya")

    await on_admin_action(cq(OWNER), AdminAction(action="users"), bot_db, access)
    assert any("🔒 @vasya" in text for text in labels(rec.last_markup))

    await on_user_toggle(
        cq(OWNER), UserAction(user_id=NEWCOMER, grant=True), bot_db, access
    )
    assert await access.has_access(NEWCOMER) is True
    # Экран перерисован уже с новым состоянием.
    assert any("✅ @vasya" in text for text in labels(rec.last_markup))


async def test_users_screen_can_revoke(cq, bot_db, access, rec, tg_bot) -> None:
    await bot_db.set_paid_status(NEWCOMER, True, username="vasya")

    await on_user_toggle(
        cq(OWNER), UserAction(user_id=NEWCOMER, grant=False), bot_db, access
    )

    assert await access.has_access(NEWCOMER) is False
    assert texts.ACCESS_REVOKED in tg_bot.to(NEWCOMER)


async def test_admin_cannot_revoke_himself_from_panel(cq, bot_db, access, rec) -> None:
    await on_user_toggle(
        cq(OWNER), UserAction(user_id=OWNER, grant=False), bot_db, access
    )
    assert texts.ADMIN_CANNOT_REVOKE_SELF in rec.alerts
    assert await access.has_access(OWNER) is True


async def test_requests_screen_lists_pending(cq, bot_db, access, rec) -> None:
    await bot_db.request_access(NEWCOMER, "vasya")

    await on_admin_action(cq(OWNER), AdminAction(action="requests"), bot_db, access)

    assert rec.has("Заявки на доступ")
    assert rec.has(str(NEWCOMER))
    assert any("Выдать" in text for text in labels(rec.last_markup))


async def test_requests_screen_when_empty(cq, bot_db, access, rec) -> None:
    await on_admin_action(cq(OWNER), AdminAction(action="requests"), bot_db, access)
    assert rec.has("Заявок нет")


async def test_stats_screen(cq, bot_db, access, rec) -> None:
    await bot_db.request_access(NEWCOMER, "vasya")
    await on_admin_action(cq(OWNER), AdminAction(action="stats"), bot_db, access)

    assert rec.has("Статистика")
    assert rec.has("Пользователей")
    assert rec.has("Лидов в базе")


async def test_admin_screens_denied_to_regular_user(cq, bot_db, access, rec) -> None:
    for action in ("panel", "users", "requests", "stats"):
        await on_admin_action(cq(USER), AdminAction(action=action), bot_db, access)
    assert rec.alerts == [texts.ERR_NO_ACCESS] * 4
    assert rec.texts == []


# --- Справка --------------------------------------------------------------


async def test_help_command(msg, bot_db, access, rec) -> None:
    await on_help(msg(), access)
    assert rec.has("Как это работает")
    assert rec.has("/menu")
    assert "◀️ В меню" in labels(rec.last_markup)


async def test_help_button_from_menu(cq, bot_db, access, rec) -> None:
    await on_help_button(cq(), access)
    assert rec.has("Как это работает")


async def test_help_requires_access(msg, bot_db, access, rec) -> None:
    await on_help(msg(STRANGER), access)
    assert rec.last_text == texts.ERR_NO_ACCESS


# --- Панель пользователя со статистикой -----------------------------------


async def test_menu_shows_personal_stats(msg, bot_db, access, rec, fsm) -> None:
    from core.models import Order
    from core.user_settings import UserSettings

    await bot_db.save_user_settings(USER, UserSettings(onboarded=True))
    order_id = await bot_db.save_order(
        Order(source="rss", external_id="1", title="t", url="u", description="d")
    )
    await bot_db.mark_delivered(USER, order_id, "черновик")
    await bot_db.save_lead(USER, order_id)

    await on_start(msg(), bot_db, access, fsm)

    assert rec.has("Получено лидов")
    assert "❓ Справка" in labels(rec.last_markup)


# --- Обработчик ошибок ----------------------------------------------------


async def test_error_handler_answers_the_user(msg) -> None:
    """Упавший хендлер не должен оставлять пользователя в тишине."""
    update = Update.model_validate(
        {"update_id": 1, "message": msg()}, context={"bot": None}
    )
    handled = await on_error(
        ErrorEvent.model_validate(
            {"update": update, "exception": RuntimeError("бум")},
            context={"bot": None},
        )
    )

    assert handled is True


async def test_error_handler_survives_undeliverable_reply() -> None:
    """Даже если ответить не получилось — обработчик не должен падать."""
    update = Update.model_validate({"update_id": 1}, context={"bot": None})
    handled = await on_error(
        ErrorEvent.model_validate(
            {"update": update, "exception": RuntimeError("бум")},
            context={"bot": None},
        )
    )
    assert handled is True

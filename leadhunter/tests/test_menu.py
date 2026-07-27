"""Тесты панели управления: меню, настройки, проверка лидов, избранное."""

from __future__ import annotations

from bot.bot import on_order_action
from bot.callbacks import EditAction, MenuAction, OrderAction
from bot.menu import on_edit_field, on_menu_action, on_menu_command
from core.models import Order
from core.user_settings import UserSettings
from tests.helpers import STRANGER, USER, labels

MENU_BUTTONS = ["⚙️ Настройки", "🔍 Проверить сейчас", "⭐ Сохранённые лиды", "🌐 Биржи"]


def _order(external_id="1", **kwargs) -> Order:
    base = dict(
        source="rss",
        external_id=external_id,
        title="Telegram бот на Python",
        url="https://example.com/1",
        description="Нужен бот для приёма заявок",
        score=90,
        category="Telegram-боты",
    )
    base.update(kwargs)
    return Order(**base)


# --- Меню -----------------------------------------------------------------


async def test_menu_command_shows_four_buttons(msg, bot_db, access, rec, fsm) -> None:
    await on_menu_command(msg(), bot_db, access, fsm)
    assert labels(rec.last_markup) == MENU_BUTTONS


async def test_menu_shows_current_filters(msg, bot_db, access, rec, fsm) -> None:
    await bot_db.save_user_settings(
        USER, UserSettings(keywords=("python",), min_budget=300, onboarded=True)
    )
    await on_menu_command(msg(), bot_db, access, fsm)

    assert rec.has("python")
    assert rec.has("300")


async def test_menu_command_denied_without_access(msg, bot_db, access, rec, fsm) -> None:
    await on_menu_command(msg(STRANGER), bot_db, access, fsm)
    assert rec.texts == []


async def test_menu_action_returns_to_menu(cq, bot_db, access, rec) -> None:
    await on_menu_action(cq(), MenuAction(action="menu"), bot_db, access)
    assert labels(rec.last_markup) == MENU_BUTTONS


async def test_menu_denies_user_without_access(cq, bot_db, access, rec) -> None:
    await on_menu_action(cq(STRANGER), MenuAction(action="check"), bot_db, access)
    assert rec.alerts == ["Нет доступа"]
    assert rec.texts == []


# --- Настройки ------------------------------------------------------------


async def test_settings_screen_offers_all_filters(cq, bot_db, access, rec) -> None:
    await on_menu_action(cq(), MenuAction(action="settings"), bot_db, access)
    assert labels(rec.last_markup) == [
        "🌐 Биржи",
        "🏷 Категории",
        "🔑 Ключевые слова",
        "💰 Бюджет",
        "◀️ В меню",
    ]


async def test_sources_button_opens_sources_in_settings_context(
    cq, bot_db, access, rec
) -> None:
    await on_menu_action(cq(), MenuAction(action="sources"), bot_db, access)

    assert rec.has("Биржи")
    assert "◀️ К настройкам" in labels(rec.last_markup)
    assert not rec.has("Шаг 1/4")  # это не мастер


async def test_edit_each_filter_opens_its_screen(cq, bot_db, access, rec) -> None:
    for field, marker in (
        ("sources", "Биржи"),
        ("categories", "Категории"),
        ("keywords", "Ключевые слова"),
        ("budget", "Минимальный бюджет"),
    ):
        await on_edit_field(cq(), EditAction(field=field), bot_db, access)
        assert rec.has(marker)
        assert "◀️ К настройкам" in labels(rec.last_markup)


async def test_edit_denied_without_access(cq, bot_db, access, rec) -> None:
    await on_edit_field(cq(STRANGER), EditAction(field="budget"), bot_db, access)
    assert rec.alerts == ["Нет доступа"]


# --- «Проверить сейчас» ---------------------------------------------------


async def test_check_finds_matching_lead(cq, bot_db, access, rec) -> None:
    await bot_db.save_order(_order(), response="r", status="new")
    await bot_db.save_user_settings(USER, UserSettings(keywords=("telegram",)))

    await on_menu_action(cq(), MenuAction(action="check"), bot_db, access)
    assert rec.has("Telegram бот на Python")
    assert rec.has("https://example.com/1")


async def test_check_applies_personal_filters(cq, bot_db, access, rec) -> None:
    """Чужой по фильтрам лид не показывается."""
    await bot_db.save_order(_order(), response="r", status="new")
    await bot_db.save_user_settings(USER, UserSettings(keywords=("wordpress",)))

    await on_menu_action(cq(), MenuAction(action="check"), bot_db, access)
    assert not rec.has("Telegram бот")
    assert rec.has("Пока ничего под твои фильтры")


async def test_check_ignores_rejected_leads(cq, bot_db, access, rec) -> None:
    await bot_db.save_order(_order("bad"), response="", status="rejected")

    await on_menu_action(cq(), MenuAction(action="check"), bot_db, access)
    assert rec.has("Пока ничего под твои фильтры")


async def test_check_respects_min_budget(cq, bot_db, access, rec) -> None:
    await bot_db.save_order(
        _order(budget_raw="$100", budget_value=100), response="r", status="new"
    )
    await bot_db.save_user_settings(USER, UserSettings(min_budget=500))

    await on_menu_action(cq(), MenuAction(action="check"), bot_db, access)
    assert not rec.has("Telegram бот")


async def test_check_is_limited(cq, bot_db, access, rec) -> None:
    from bot.screens import LEADS_LIMIT

    for i in range(LEADS_LIMIT + 5):
        await bot_db.save_order(_order(str(i)), response="r", status="new")

    await on_menu_action(cq(), MenuAction(action="check"), bot_db, access)
    assert rec.last_text.count("🔹") == LEADS_LIMIT


# --- Избранное ------------------------------------------------------------


async def test_saved_is_empty_by_default(cq, bot_db, access, rec) -> None:
    await on_menu_action(cq(), MenuAction(action="saved"), bot_db, access)
    assert rec.has("Тут пусто")


async def test_save_lead_from_card_then_see_it_in_menu(cq, bot_db, access, rec, fsm) -> None:
    order_id = await bot_db.save_order(_order(), response="r", status="new")

    await on_order_action(
        cq(), OrderAction(action="save", order_id=order_id), bot_db, access, fsm
    )
    assert "Сохранено ❤️" in rec.alerts
    assert await bot_db.is_lead_saved(USER, order_id) is True

    await on_menu_action(cq(), MenuAction(action="saved"), bot_db, access)
    assert rec.has("Telegram бот на Python")


async def test_unsave_lead_from_card(cq, bot_db, access, rec, fsm) -> None:
    order_id = await bot_db.save_order(_order(), response="r", status="new")
    await bot_db.save_lead(USER, order_id)

    await on_order_action(
        cq(), OrderAction(action="unsave", order_id=order_id), bot_db, access, fsm
    )
    assert await bot_db.is_lead_saved(USER, order_id) is False

    await on_menu_action(cq(), MenuAction(action="saved"), bot_db, access)
    assert rec.has("Тут пусто")


async def test_saved_leads_are_not_shared_between_users(cq, bot_db, access, rec) -> None:
    order_id = await bot_db.save_order(_order(), response="r", status="new")
    await bot_db.save_lead(USER, order_id)
    await bot_db.set_paid_status(STRANGER, True)

    await on_menu_action(cq(STRANGER), MenuAction(action="saved"), bot_db, access)
    assert rec.has("Тут пусто")


async def test_card_save_button_reflects_state(cq, bot_db, access, rec, fsm) -> None:
    order_id = await bot_db.save_order(_order(), response="r", status="new")

    await on_order_action(
        cq(), OrderAction(action="save", order_id=order_id), bot_db, access, fsm
    )
    assert "💔 Убрать из сохранённых" in labels(rec.last_markup)

    await on_order_action(
        cq(), OrderAction(action="unsave", order_id=order_id), bot_db, access, fsm
    )
    assert "❤️ Сохранить" in labels(rec.last_markup)


async def test_save_denied_without_access(cq, bot_db, access, rec, fsm) -> None:
    order_id = await bot_db.save_order(_order(), response="r", status="new")

    await on_order_action(
        cq(STRANGER), OrderAction(action="save", order_id=order_id), bot_db, access, fsm
    )
    assert rec.alerts == ["Нет доступа"]
    assert await bot_db.is_lead_saved(STRANGER, order_id) is False

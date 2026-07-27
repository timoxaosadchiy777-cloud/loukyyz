"""Экран «Биржи»: персональный выбор, массовые кнопки и проверка вручную.

Требование, вокруг которого всё построено: список включённых бирж НЕ фиксирован,
его задаёт каждый пользователь под своим telegram_id, и выключенная биржа не
опрашивается.
"""

from __future__ import annotations

from bot import texts
from bot.callbacks import CTX_SETTINGS, CTX_WIZARD, EditAction, MenuAction, SourceAction, ToggleAction
from bot.menu import on_edit_field, on_menu_action
from bot.wizard import on_source_action, on_soon, on_toggle
from core.sources import default_enabled_ids
from tests.helpers import STRANGER, USER, buttons, callback_for, labels

OTHER = 501


class _Supervisor:
    """Подставной супервизор: помнит, что «опрашивается», и считает проверки."""

    def __init__(self, active=(), blocked=(), found: int | None = 3) -> None:
        self.active = set(active)
        self.blocked = set(blocked)
        self.reconciled = 0
        self.polled: list[str] = []
        self._found = found
        self.error: Exception | None = None

    async def reconcile(self):
        self.reconciled += 1
        return set(), set()

    async def poll_now(self, source_id: str):
        self.polled.append(source_id)
        if self.error is not None:
            raise self.error
        return self._found


def _row_for(markup, label_part: str) -> str:
    for text in labels(markup):
        if label_part in text:
            return text
    raise AssertionError(f"{label_part!r} нет среди {labels(markup)}")


# --- Состояния 🟢 / ⚪ / 🔴 -------------------------------------------------


async def test_states_reflect_personal_choice(cq, bot_db, access, rec) -> None:
    await on_menu_action(cq(), MenuAction(action="sources"), bot_db, access)

    assert _row_for(rec.last_markup, "Upwork").startswith("🟢")
    assert _row_for(rec.last_markup, "Kwork.ru").startswith("🟢")
    assert _row_for(rec.last_markup, "WeWorkRemotely").startswith("⚪")
    assert _row_for(rec.last_markup, "Fiverr").startswith("🔴")


async def test_defaults_match_the_registry(bot_db) -> None:
    settings = await bot_db.get_user_settings(USER)
    assert settings.sources == default_enabled_ids()
    assert settings.source_enabled("upwork") is True
    assert settings.source_enabled("weworkremotely") is False


async def test_toggle_flips_the_state_on_screen(cq, bot_db, access, rec) -> None:
    await on_toggle(cq(), ToggleAction(kind="src", value="guru", ctx=CTX_SETTINGS), bot_db, access)

    assert _row_for(rec.last_markup, "Guru").startswith("⚪")
    assert "guru" not in await bot_db.get_enabled_sources(USER)


async def test_choice_is_per_telegram_user(cq, bot_db, access) -> None:
    """Один выключил Upwork — у другого он остаётся включённым."""
    await bot_db.set_paid_status(OTHER, True)
    await on_toggle(cq(), ToggleAction(kind="src", value="upwork", ctx=CTX_SETTINGS), bot_db, access)

    assert "upwork" not in await bot_db.get_enabled_sources(USER)
    assert "upwork" in await bot_db.get_enabled_sources(OTHER)


async def test_source_without_parser_cannot_be_enabled(cq, bot_db, access, rec) -> None:
    await on_soon(cq(), ToggleAction(kind="soon", value="fiverr", ctx=CTX_SETTINGS))

    assert texts.SOURCE_SOON in rec.alerts[0]
    assert "Buyer Requests" in rec.alerts[0]  # объясняем причину, а не «скоро»
    assert "fiverr" not in await bot_db.get_enabled_sources(USER)


# --- «Выбрать все» / «Отключить все» --------------------------------------


async def test_select_all_enables_every_available_source(cq, bot_db, access, rec) -> None:
    await on_source_action(cq(), SourceAction(action="all", ctx=CTX_SETTINGS), bot_db, access)

    enabled = await bot_db.get_enabled_sources(USER)
    assert "weworkremotely" in enabled and "upwork" in enabled
    assert "fiverr" not in enabled  # парсера нет — включить нечего
    assert _row_for(rec.last_markup, "WeWorkRemotely").startswith("🟢")


async def test_disable_all_stops_everything(cq, bot_db, access, rec) -> None:
    await on_source_action(cq(), SourceAction(action="none", ctx=CTX_SETTINGS), bot_db, access)

    assert await bot_db.get_enabled_sources(USER) == ()
    assert all(not text.startswith("🟢") for text in labels(rec.last_markup))


async def test_disable_all_is_not_read_as_all_enabled(cq, bot_db, access) -> None:
    """Пустой список должен означать «ничего», иначе выключение бессмысленно."""
    await on_source_action(cq(), SourceAction(action="none", ctx=CTX_SETTINGS), bot_db, access)

    settings = await bot_db.get_user_settings(USER)
    assert settings.source_enabled("kwork") is False


async def test_bulk_buttons_are_on_the_screen(cq, bot_db, access, rec) -> None:
    await on_menu_action(cq(), MenuAction(action="sources"), bot_db, access)

    assert callback_for(rec.last_markup, "Выбрать все") == SourceAction(
        action="all", ctx=CTX_SETTINGS
    ).pack()
    assert callback_for(rec.last_markup, "Отключить все") == SourceAction(
        action="none", ctx=CTX_SETTINGS
    ).pack()


# --- «🔄 Проверить сейчас» -------------------------------------------------


async def test_poll_button_only_for_enabled_sources(cq, bot_db, access, rec) -> None:
    await on_toggle(cq(), ToggleAction(kind="src", value="guru", ctx=CTX_SETTINGS), bot_db, access)

    polls = [data for text, data in buttons(rec.last_markup) if text == "🔄"]
    assert SourceAction(action="poll", value="kwork", ctx=CTX_SETTINGS).pack() in polls
    assert SourceAction(action="poll", value="guru", ctx=CTX_SETTINGS).pack() not in polls


async def test_poll_button_absent_in_wizard(cq, bot_db, access, rec) -> None:
    """В мастере проверять нечего — экран не загромождаем."""
    await on_toggle(cq(), ToggleAction(kind="src", value="guru", ctx=CTX_WIZARD), bot_db, access)
    assert "🔄" not in labels(rec.last_markup)


async def test_poll_now_reports_what_was_found(cq, bot_db, access, rec) -> None:
    supervisor = _Supervisor(active={"guru"}, found=4)
    await on_source_action(
        cq(), SourceAction(action="poll", value="guru", ctx=CTX_SETTINGS),
        bot_db, access, supervisor,
    )

    assert supervisor.polled == ["guru"]
    assert "4" in rec.alerts[0]


async def test_poll_now_explains_missing_setup(cq, bot_db, access, rec) -> None:
    """Upwork включён, но ленты нет — говорим, какую переменную заполнить."""
    await on_source_action(
        cq(), SourceAction(action="poll", value="upwork", ctx=CTX_SETTINGS),
        bot_db, access, _Supervisor(active=set()),
    )
    assert "UPWORK_RSS_URL" in rec.alerts[0]


async def test_poll_now_shows_the_real_error(cq, bot_db, access, rec) -> None:
    supervisor = _Supervisor(active={"guru"})
    supervisor.error = RuntimeError("HTTP 403 — биржа забанила")
    await on_source_action(
        cq(), SourceAction(action="poll", value="guru", ctx=CTX_SETTINGS),
        bot_db, access, supervisor,
    )
    assert "403" in rec.alerts[0]


async def test_poll_now_without_supervisor_does_not_crash(cq, bot_db, access, rec) -> None:
    await on_source_action(
        cq(), SourceAction(action="poll", value="guru", ctx=CTX_SETTINGS), bot_db, access
    )
    assert rec.alerts == [texts.SOURCE_CHECK_OFFLINE]


# --- Связь экрана с парсерами ---------------------------------------------


async def test_toggle_reconciles_parsers_immediately(cq, bot_db, access) -> None:
    """Включение биржи должно поднимать парсер, а не ждать фонового прохода."""
    supervisor = _Supervisor()
    await on_toggle(
        cq(), ToggleAction(kind="src", value="guru", ctx=CTX_SETTINGS),
        bot_db, access, supervisor,
    )
    assert supervisor.reconciled == 1


async def test_screen_warns_about_enabled_but_silent_source(cq, bot_db, access, rec) -> None:
    await on_edit_field(
        cq(), EditAction(field="sources"), bot_db, access,
        _Supervisor(active={"kwork", "kwork_com", "freelancer", "peopleperhour", "guru"}),
    )
    assert "UPWORK_RSS_URL" in rec.last_text  # опрос не идёт — сказано почему


async def test_screen_warns_about_owner_block(cq, bot_db, access, rec) -> None:
    await on_edit_field(
        cq(), EditAction(field="sources"), bot_db, access,
        _Supervisor(active={"kwork"}, blocked={"guru"}),
    )
    assert "settings.yaml" in rec.last_text


async def test_no_warnings_when_everything_polls(cq, bot_db, access, rec) -> None:
    settings = await bot_db.get_user_settings(USER)
    await on_edit_field(
        cq(), EditAction(field="sources"), bot_db, access,
        _Supervisor(active=set(settings.sources)),
    )
    assert "⚠️" not in rec.last_text


async def test_screen_without_supervisor_shows_no_false_alarm(cq, bot_db, access, rec) -> None:
    """Супервизора нет — состояние опроса неизвестно, врать не о чем."""
    await on_menu_action(cq(), MenuAction(action="sources"), bot_db, access)
    assert "⚠️" not in rec.last_text


# --- Доступ ---------------------------------------------------------------


async def test_stranger_cannot_touch_sources(cq, bot_db, access, rec) -> None:
    supervisor = _Supervisor(active={"guru"})
    await on_source_action(
        cq(STRANGER), SourceAction(action="none", ctx=CTX_SETTINGS), bot_db, access, supervisor
    )
    await on_source_action(
        cq(STRANGER), SourceAction(action="poll", value="guru", ctx=CTX_SETTINGS),
        bot_db, access, supervisor,
    )

    assert rec.alerts == [texts.ERR_NO_ACCESS] * 2
    assert supervisor.polled == []
    assert await bot_db.get_enabled_sources(STRANGER) == default_enabled_ids()

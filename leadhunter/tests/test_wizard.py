"""Тесты мастера онбординга: шаги, переключатели, ввод своих ключевых слов."""

from __future__ import annotations

from bot import texts
from bot.bot import on_start
from bot.callbacks import CTX_SETTINGS, CTX_WIZARD, BudgetAction, ToggleAction, WizardAction
from bot.wizard import (
    WizardStates,
    on_budget,
    on_keywords_text,
    on_soon,
    on_toggle,
    on_wizard_step,
)
from core.user_settings import CATEGORIES, KEYWORD_PRESETS, UserSettings
from tests.helpers import STRANGER, USER, callback_for, labels


# --- Запуск мастера из /start --------------------------------------------


async def test_start_launches_wizard_for_new_user(msg, bot_db, access, rec, fsm) -> None:
    await on_start(msg(), bot_db, access, fsm)

    assert rec.has("Настроим бота под тебя")
    assert rec.has("Шаг 1/4")
    assert "🌐 RSS / джоб-борды" in " ".join(labels(rec.last_markup))


async def test_start_shows_menu_for_onboarded_user(msg, bot_db, access, rec, fsm) -> None:
    await bot_db.save_user_settings(USER, UserSettings(onboarded=True))
    await on_start(msg(), bot_db, access, fsm)

    assert rec.has("LeadHunter")
    assert "⚙️ Настройки" in labels(rec.last_markup)
    assert not rec.has("Шаг 1/4")


async def test_start_without_access_shows_id_not_wizard(msg, bot_db, access, rec, fsm) -> None:
    await on_start(msg(STRANGER), bot_db, access, fsm)

    assert rec.has("Доступ выдаёт администратор")
    assert rec.has(str(STRANGER))
    assert not rec.has("Шаг 1/4")


# --- Шаг «Биржи» ----------------------------------------------------------


async def test_kwork_is_selectable(cq, msg, bot_db, access, rec, fsm) -> None:
    """Парсер Kwork готов — площадка выбирается как обычная."""
    await on_start(msg(), bot_db, access, fsm)
    assert any("Kwork" in text and "скоро" not in text for text in labels(rec.last_markup))

    await on_toggle(
        cq(), ToggleAction(kind="src", value="kwork", ctx=CTX_WIZARD), bot_db, access
    )
    assert "kwork" not in (await bot_db.get_user_settings(USER)).sources


async def test_planned_source_reports_soon(cq, rec) -> None:
    """Кнопка-заглушка для площадки без парсера ничего не меняет."""
    await on_soon(cq(), ToggleAction(kind="soon", value="future", ctx=CTX_WIZARD))
    assert texts.SOURCE_SOON in rec.alerts


async def test_toggle_source_persists_and_redraws(cq, bot_db, access, rec) -> None:
    await on_toggle(
        cq(), ToggleAction(kind="src", value="rss", ctx=CTX_WIZARD), bot_db, access
    )

    # Первое выключение = «все, кроме этой».
    assert (await bot_db.get_user_settings(USER)).sources == (
        "upwork", "fiverr", "kwork", "kwork_com",
    )
    assert any("▫️ 🌐 RSS" in text for text in labels(rec.last_markup))


async def test_toggle_source_twice_returns_it(cq, bot_db, access) -> None:
    for _ in range(2):
        await on_toggle(
            cq(), ToggleAction(kind="src", value="rss", ctx=CTX_WIZARD), bot_db, access
        )
    settings = await bot_db.get_user_settings(USER)
    assert settings.source_enabled("rss") is True


# --- Категории и ключевые слова ------------------------------------------


async def test_toggle_category_by_index(cq, bot_db, access, rec) -> None:
    await on_toggle(
        cq(), ToggleAction(kind="cat", value="0", ctx=CTX_WIZARD), bot_db, access
    )
    assert (await bot_db.get_user_settings(USER)).categories == (CATEGORIES[0],)


async def test_toggle_keyword_by_index(cq, bot_db, access) -> None:
    await on_toggle(
        cq(), ToggleAction(kind="kw", value="1", ctx=CTX_WIZARD), bot_db, access
    )
    assert (await bot_db.get_user_settings(USER)).keywords == (KEYWORD_PRESETS[1],)


async def test_out_of_range_index_is_ignored(cq, bot_db, access) -> None:
    """callback_data приходит извне — некорректный индекс не должен ронять бота."""
    await on_toggle(
        cq(), ToggleAction(kind="cat", value="999", ctx=CTX_WIZARD), bot_db, access
    )
    await on_toggle(
        cq(), ToggleAction(kind="kw", value="abc", ctx=CTX_WIZARD), bot_db, access
    )
    settings = await bot_db.get_user_settings(USER)
    assert settings.categories == ()
    assert settings.keywords == ()


# --- Бюджет и завершение --------------------------------------------------


async def test_budget_selection_persists(cq, bot_db, access, rec) -> None:
    await on_budget(cq(), BudgetAction(value=300, ctx=CTX_WIZARD), bot_db, access)

    assert (await bot_db.get_user_settings(USER)).min_budget == 300
    assert any("✅ от 300$" in text for text in labels(rec.last_markup))


async def test_navigation_between_steps(cq, bot_db, access, fsm, rec) -> None:
    for step, marker in (
        ("categories", "Шаг 2/4"),
        ("keywords", "Шаг 3/4"),
        ("budget", "Шаг 4/4"),
    ):
        await on_wizard_step(
            cq(), WizardAction(step=step, ctx=CTX_WIZARD), bot_db, access, fsm
        )
        assert rec.has(marker)

    # На последнем шаге вместо «Далее» — «Готово».
    assert "✅ Готово" in labels(rec.last_markup)


async def test_done_marks_onboarded_and_opens_menu(cq, bot_db, access, fsm, rec) -> None:
    await on_wizard_step(
        cq(), WizardAction(step="done", ctx=CTX_WIZARD), bot_db, access, fsm
    )

    assert (await bot_db.get_user_settings(USER)).onboarded is True
    assert "🔍 Проверить сейчас" in labels(rec.last_markup)


async def test_toggles_before_done_do_not_finish_onboarding(cq, bot_db, access) -> None:
    """Брошенный мастер сохраняет выбор, но не считается пройденным."""
    await on_toggle(
        cq(), ToggleAction(kind="kw", value="0", ctx=CTX_WIZARD), bot_db, access
    )
    settings = await bot_db.get_user_settings(USER)
    assert settings.keywords == (KEYWORD_PRESETS[0],)
    assert settings.onboarded is False


# --- Свои ключевые слова (единственный текстовый ввод) --------------------


async def test_custom_keywords_flow(cq, msg, bot_db, access, fsm, rec) -> None:
    await on_wizard_step(
        cq(), WizardAction(step="kw_input", ctx=CTX_WIZARD), bot_db, access, fsm
    )
    assert rec.has("Свои ключевые слова")
    assert await fsm.get_state() == WizardStates.keywords

    await on_keywords_text(
        msg(text="парсинг, Google Sheets"), bot_db, access, fsm
    )

    assert (await bot_db.get_user_settings(USER)).keywords == ("парсинг", "google sheets")
    assert await fsm.get_state() is None  # состояние снято
    assert rec.has("Шаг 3/4")  # вернулись в мастер


async def test_custom_keywords_from_settings_returns_to_settings(
    cq, msg, bot_db, access, fsm, rec
) -> None:
    await on_wizard_step(
        cq(), WizardAction(step="kw_input", ctx=CTX_SETTINGS), bot_db, access, fsm
    )
    await on_keywords_text(msg(text="django"), bot_db, access, fsm)

    assert rec.has("Настройки")
    assert "🔑 Ключевые слова" in labels(rec.last_markup)


async def test_custom_keywords_merge_with_presets(msg, bot_db, access, fsm) -> None:
    await bot_db.save_user_settings(USER, UserSettings(keywords=("python",)))
    await fsm.set_state(WizardStates.keywords)

    await on_keywords_text(msg(text="парсинг"), bot_db, access, fsm)
    assert (await bot_db.get_user_settings(USER)).keywords == ("python", "парсинг")


# --- Контекст экрана ------------------------------------------------------


async def test_settings_context_offers_return_to_settings(cq, bot_db, access, rec) -> None:
    await on_toggle(
        cq(), ToggleAction(kind="src", value="rss", ctx=CTX_SETTINGS), bot_db, access
    )
    assert "◀️ К настройкам" in labels(rec.last_markup)
    assert "Далее ▶️" not in labels(rec.last_markup)


async def test_wizard_context_offers_next(cq, bot_db, access, rec) -> None:
    await on_toggle(
        cq(), ToggleAction(kind="src", value="rss", ctx=CTX_WIZARD), bot_db, access
    )
    assert "Далее ▶️" in labels(rec.last_markup)


async def test_step_callbacks_round_trip_through_keyboard(msg, bot_db, access, rec, fsm) -> None:
    """Кнопка «Далее» действительно ведёт на следующий шаг."""
    await on_start(msg(), bot_db, access, fsm)
    data = callback_for(rec.last_markup, "Далее")
    assert data == WizardAction(step="categories", ctx=CTX_WIZARD).pack()


# --- Доступ ---------------------------------------------------------------


async def test_wizard_denies_user_without_access(cq, bot_db, access, fsm, rec) -> None:
    await on_wizard_step(
        cq(STRANGER), WizardAction(step="done", ctx=CTX_WIZARD), bot_db, access, fsm
    )
    await on_toggle(
        cq(STRANGER),
        ToggleAction(kind="src", value="rss", ctx=CTX_WIZARD),
        bot_db,
        access,
    )
    await on_budget(
        cq(STRANGER), BudgetAction(value=100, ctx=CTX_WIZARD), bot_db, access
    )

    assert rec.alerts == [texts.ERR_NO_ACCESS] * 3
    assert (await bot_db.get_user_settings(STRANGER)) == UserSettings()


async def test_start_cancels_pending_keyword_input(msg, bot_db, access, fsm, rec) -> None:
    """Иначе следующее сообщение пользователя молча уйдёт в фильтр."""
    await fsm.set_state(WizardStates.keywords)
    await on_start(msg(), bot_db, access, fsm)
    assert await fsm.get_state() is None


async def test_menu_cancels_pending_keyword_input(msg, bot_db, access, fsm) -> None:
    from bot.menu import on_menu_command

    await fsm.set_state(WizardStates.keywords)
    await on_menu_command(msg(), bot_db, access, fsm)
    assert await fsm.get_state() is None

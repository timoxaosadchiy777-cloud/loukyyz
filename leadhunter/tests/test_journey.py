"""Сквозной путь клиента — от первого /start до перезапуска бота.

Отдельные узлы покрыты своими тестами; здесь проверяется, что они складываются
в работающий продукт. Именно этот сценарий проходит покупатель, поэтому его
поломка означает «продукт не работает», даже если все юнит-тесты зелёные.
"""

from __future__ import annotations

import pytest
import pytest_asyncio

from ai.scoring import LeadScore
from bot.access import AccessControl
from bot.admin import on_access_decision
from bot.bot import on_access_request, on_order_action, on_start
from bot.callbacks import (
    CTX_WIZARD,
    AccessAction,
    BudgetAction,
    MenuAction,
    OrderAction,
    ToggleAction,
    WizardAction,
)
from bot.menu import on_menu_action
from bot.wizard import on_budget, on_toggle, on_wizard_step
from core.models import LeadState, Order
from core.runtime_config import RuntimeConfig, RuntimeConfigStore
from database.db import Database
from main import handle_order
from tests.helpers import OWNER, labels

CLIENT = 5150


# --- Заглушки внешнего мира ------------------------------------------------


class _Scorer:
    def __init__(self) -> None:
        self.calls = 0

    async def score(self, order: Order) -> LeadScore:
        self.calls += 1
        return LeadScore(
            score=88, category="Telegram-боты", reason="по профилю",
            probability_of_sale=70, should_send=True,
            technology="python, aiogram", summary="Бот приёма заявок",
        )


class _Responder:
    def __init__(self) -> None:
        self.calls = 0

    async def generate(self, order, analysis=None) -> str:
        self.calls += 1
        return "Готов взяться: сделаю бота на aiogram с админкой."


class _LLM:
    last_error = None


class _Alerter:
    async def alert(self, text: str, key: str | None = None) -> None:
        pass


class _PushBot:
    """Ловит карточки, которые пайплайн рассылает получателям."""

    def __init__(self) -> None:
        self.sent: list[tuple[int, str]] = []

    async def send_message(self, chat_id: int, text: str, **kwargs):
        self.sent.append((chat_id, text))

    def to(self, chat_id: int) -> list[str]:
        return [text for target, text in self.sent if target == chat_id]


class _Settings:
    owner_id = OWNER


@pytest_asyncio.fixture
async def journey_db(tmp_path):
    """Свежая база: клиент ещё никто, доступа нет."""
    db = Database(str(tmp_path / "journey.db"))
    await db.connect()
    try:
        yield db
    finally:
        await db.close()


@pytest.fixture
def journey_access(journey_db) -> AccessControl:
    return AccessControl(journey_db, owner_id=OWNER)


@pytest.fixture
def config(tmp_path):
    return RuntimeConfigStore(
        tmp_path / "settings.yaml", defaults=RuntimeConfig(min_score=60, min_budget=0)
    )


def _lead(external_id: str = "j-1") -> Order:
    return Order(
        source="rss",
        external_id=external_id,
        title="Нужен Telegram бот на Python",
        url="https://example.com/j1",
        description="Бот приёма заявок с выгрузкой в таблицы",
        budget_raw="$500",
        budget_value=500,
    )


async def _run_pipeline(db, config, order, bot, scorer=None, responder=None):
    await handle_order(
        order,
        db=db,
        scorer=scorer or _Scorer(),
        responder=responder or _Responder(),
        llm=_LLM(),
        bot=bot,
        alerter=_Alerter(),
        settings=_Settings(),
        config=config,
    )


# --- Полный путь -----------------------------------------------------------


async def test_full_client_journey(
    journey_db, journey_access, config, msg, cq, rec, fsm, tg_bot
) -> None:
    db, access = journey_db, journey_access

    # 1. Новый пользователь жмёт /start и видит продающий экран с кнопкой заявки.
    await on_start(msg(CLIENT), db, access, fsm)
    assert rec.has("заказы с фриланс-бирж")
    assert "📨 Запросить доступ" in labels(rec.last_markup)

    # 2. Заявка уходит администратору с кнопками решения.
    await on_access_request(
        cq(CLIENT), AccessAction(action="request", user_id=CLIENT), db, OWNER
    )
    assert tg_bot.chats == [OWNER]
    assert "✅ Выдать доступ" in labels(tg_bot.markup_for(OWNER))

    # 3. Администратор выдаёт доступ — клиент получает уведомление.
    await on_access_decision(
        cq(OWNER), AccessAction(action="grant", user_id=CLIENT), db, access
    )
    assert await access.has_access(CLIENT) is True
    assert any("Доступ открыт" in t for t in tg_bot.to(CLIENT))

    # 4. Повторный /start ведёт в мастер настройки.
    await on_start(msg(CLIENT), db, access, fsm)
    assert rec.has("Шаг 1/4")

    # 5. Клиент настраивает фильтры: биржа, ключевое слово, бюджет.
    await on_toggle(
        cq(CLIENT), ToggleAction(kind="kw", value="0", ctx=CTX_WIZARD), db, access
    )
    await on_budget(cq(CLIENT), BudgetAction(value=100, ctx=CTX_WIZARD), db, access)
    await on_wizard_step(
        cq(CLIENT), WizardAction(step="done", ctx=CTX_WIZARD), db, access, fsm
    )

    settings = await db.get_user_settings(CLIENT)
    assert settings.onboarded is True
    assert settings.min_budget == 100
    assert settings.keywords  # выбранное ключевое слово сохранилось

    # 6. Приходит лид — пайплайн доставляет его и владельцу, и клиенту.
    push = _PushBot()
    scorer, responder = _Scorer(), _Responder()
    await _run_pipeline(db, config, _lead(), push, scorer, responder)

    assert CLIENT in [chat for chat, _ in push.sent]
    assert scorer.calls == 1      # один анализ на лид, а не на получателя
    assert responder.calls == 1   # и один отклик

    order_id = (await db.recent_orders())[0]["id"]
    assert await db.was_delivered(CLIENT, order_id) is True

    # 7. Клиент сохраняет лид — он появляется в «Сохранённых».
    await on_order_action(
        cq(CLIENT), OrderAction(action="save", order_id=order_id), db, access, fsm
    )
    assert await db.is_lead_saved(CLIENT, order_id) is True

    await on_menu_action(cq(CLIENT), MenuAction(action="saved"), db, access)
    assert rec.has("Telegram бот")

    # 8. Копирует отклик — получает готовый текст.
    await on_order_action(
        cq(CLIENT), OrderAction(action="copy", order_id=order_id), db, access, fsm
    )
    assert rec.has("Готов взяться")

    # 9. Пишет свой вариант — он сохраняется только у него.
    await db.set_delivery_response(CLIENT, order_id, "мой личный текст")
    await on_order_action(
        cq(CLIENT), OrderAction(action="copy", order_id=order_id), db, access, fsm
    )
    assert rec.has("мой личный текст")
    assert (await db.get_delivery(OWNER, order_id))["response"] != "мой личный текст"


async def test_state_survives_restart(tmp_path, msg, cq, rec, fsm) -> None:
    """После перезапуска бота у клиента на месте доступ, фильтры и избранное."""
    path = tmp_path / "restart.db"

    db = Database(str(path))
    await db.connect()
    access = AccessControl(db, owner_id=OWNER)
    await db.set_paid_status(CLIENT, True)
    from core.user_settings import UserSettings

    await db.save_user_settings(
        CLIENT, UserSettings(keywords=("python",), min_budget=200, onboarded=True)
    )
    order_id = await db.save_order(_lead(), response="черновик", status="new")
    await db.mark_delivered(CLIENT, order_id, "черновик")
    await db.save_lead(CLIENT, order_id)
    await db.close()

    # Перезапуск процесса: то же хранилище, новое подключение.
    db = Database(str(path))
    await db.connect()
    access = AccessControl(db, owner_id=OWNER)
    try:
        assert await access.has_access(CLIENT) is True
        settings = await db.get_user_settings(CLIENT)
        assert settings.onboarded is True
        assert settings.min_budget == 200
        assert await db.is_lead_saved(CLIENT, order_id) is True

        # И меню открывается сразу, без повторного мастера.
        await on_start(msg(CLIENT), db, access, fsm)
        assert not rec.has("Шаг 1/4")
        assert "⚙️ Настройки" in labels(rec.last_markup)
    finally:
        await db.close()


async def test_lead_is_not_redelivered_after_restart(tmp_path, config) -> None:
    """Тот же лид после перезапуска не приходит клиенту повторно."""
    path = tmp_path / "dedup.db"

    db = Database(str(path))
    await db.connect()
    await db.set_paid_status(CLIENT, True)
    push = _PushBot()
    await _run_pipeline(db, config, _lead(), push)
    assert CLIENT in [chat for chat, _ in push.sent]
    await db.close()

    db = Database(str(path))
    await db.connect()
    try:
        again = _PushBot()
        await _run_pipeline(db, config, _lead(), again)
        assert again.sent == []
    finally:
        await db.close()


async def test_revoked_client_loses_everything_but_keeps_data(
    journey_db, journey_access, config, cq, rec, fsm
) -> None:
    """Отзыв доступа закрывает бота, но настройки и избранное не теряются."""
    db, access = journey_db, journey_access
    from core.user_settings import UserSettings

    await db.set_paid_status(CLIENT, True)
    await db.save_user_settings(CLIENT, UserSettings(min_budget=300, onboarded=True))
    order_id = await db.save_order(_lead(), response="ч", status="new")
    await db.mark_delivered(CLIENT, order_id, "ч")
    await db.save_lead(CLIENT, order_id)

    await db.set_paid_status(CLIENT, False)

    assert await access.has_access(CLIENT) is False
    await on_menu_action(cq(CLIENT), MenuAction(action="saved"), db, access)
    assert rec.alerts  # бот отказал

    # Данные на месте: при возобновлении подписки всё вернётся.
    assert (await db.get_user_settings(CLIENT)).min_budget == 300
    assert await db.is_lead_saved(CLIENT, order_id) is True

    await db.set_paid_status(CLIENT, True)
    assert await access.has_access(CLIENT) is True


async def test_lead_not_matching_filters_never_reaches_client(
    journey_db, config
) -> None:
    """Клиент платит за релевантность: чужой лид не должен приходить."""
    db = journey_db
    from core.user_settings import UserSettings

    await db.set_paid_status(CLIENT, True)
    await db.save_user_settings(CLIENT, UserSettings(keywords=("wordpress",)))
    await db.save_user_settings(OWNER, UserSettings(keywords=("wordpress",)))

    push = _PushBot()
    scorer = _Scorer()
    await _run_pipeline(db, config, _lead(), push, scorer)

    assert push.sent == []
    assert scorer.calls == 0  # и денег на ИИ это не стоило


async def test_regeneration_is_rate_limited(
    journey_db, journey_access, cq, rec, fsm
) -> None:
    """Кнопка «сгенерировать заново» тратит деньги — её нельзя жать бесконечно."""
    from bot.bot import _regen_limiter

    db, access = journey_db, journey_access
    await db.set_paid_status(CLIENT, True)
    order_id = await db.save_order(_lead(), response="ч", status="new")
    await db.mark_delivered(CLIENT, order_id, "ч")

    responder = _Responder()
    _regen_limiter.reset(CLIENT)
    for _ in range(_regen_limiter.limit + 3):
        await on_order_action(
            cq(CLIENT),
            OrderAction(action="regen", order_id=order_id),
            db,
            access,
            fsm,
            responder,
        )

    assert responder.calls == _regen_limiter.limit
    assert any("Слишком часто" in a for a in rec.alerts)
    _regen_limiter.reset(CLIENT)


# --- Лимит длины сообщения Telegram ---------------------------------------


def test_card_always_fits_telegram_limit() -> None:
    """Длинный отклик раньше рвал отправку — клиент молча терял лид."""
    from bot.cards import TELEGRAM_LIMIT, render_card

    order = Order(
        source="rss", external_id="1", title="Т" * 400,
        url="https://example.com/" + "x" * 200, description="d",
        score=90, category="К" * 100, reason="П" * 600,
        technology="т" * 200, summary="с" * 500,
        probability_of_sale=70, budget_raw="$500",
    )
    for response in ("О" * 5000, "&" * 4000, "<b>" * 1000, ""):
        card = render_card(order, response)
        assert len(card) <= TELEGRAM_LIMIT


def test_short_card_is_untouched() -> None:
    from bot.cards import render_card

    order = Order(source="rss", external_id="1", title="Бот",
                  url="https://example.com/1", description="d", score=90)
    card = render_card(order, "Готов взяться за проект.")
    assert "Готов взяться за проект." in card
    assert "…" not in card


def test_long_response_is_split_not_truncated() -> None:
    """Отклик обрезать нельзя — пользователю нужен весь текст."""
    from bot.cards import TELEGRAM_LIMIT, split_plain

    text = "предложение " * 1500
    parts = split_plain(text)

    assert len(parts) > 1
    assert all(len(p) <= TELEGRAM_LIMIT for p in parts)
    assert "".join(parts).replace(" ", "") == text.replace(" ", "")


def test_lead_list_fits_limit() -> None:
    from bot.cards import TELEGRAM_LIMIT
    from bot.screens import render_leads

    class _Row(dict):
        def __getitem__(self, key):
            return super().__getitem__(key)

    rows = [
        _Row(
            id=i, source="rss", external_id=str(i), title="З" * 400,
            url="https://example.com/" + "y" * 200, description="d",
            budget_raw="", budget_value=None, score=90, category="К" * 80,
            reason="", probability_of_sale=None, should_send=1,
            technology="", summary="", crm_status="new", budget_currency="USD",
        )
        for i in range(10)
    ]
    text = render_leads(rows, title="🔍 Лиды", empty="пусто")
    assert len(text) <= TELEGRAM_LIMIT
    assert "и ещё" in text


# --- Первый опыт покупателя ------------------------------------------------


def test_empty_config_is_explained_not_crashed() -> None:
    """Покупатель с пустым .env должен получить инструкцию, а не трейсбек."""
    from main import check_configuration

    class _Empty:
        bot_token = ""
        owner_id = 0
        dev_mode = False

    problems = check_configuration(_Empty())
    assert any("BOT_TOKEN" in p and "@BotFather" in p for p in problems)
    assert any("OWNER_ID" in p and "@userinfobot" in p for p in problems)


def test_malformed_token_is_caught_before_start() -> None:
    from main import check_configuration

    class _Bad:
        bot_token = "просто-строка"
        owner_id = 100
        dev_mode = False

    assert any("не похож на токен" in p for p in check_configuration(_Bad()))


def test_valid_config_passes() -> None:
    from main import check_configuration

    class _Ok:
        bot_token = "123456:AAHdqTcvCH1vGWJxfSeofSAs0K5PALDsaw"
        owner_id = 100
        dev_mode = False

    assert check_configuration(_Ok()) == []


async def test_repeat_requests_do_not_flood_admin(
    journey_db, cq, rec, tg_bot
) -> None:
    """После отказа заявку можно подать снова, но не бесконечно."""
    from bot.bot import _request_limiter, on_access_request
    from bot.callbacks import AccessAction

    db = journey_db
    _request_limiter.reset(CLIENT)
    action = AccessAction(action="request", user_id=CLIENT)

    for _ in range(6):
        await on_access_request(cq(CLIENT), action, db, OWNER)
        # Администратор отклонил — заявка снята, можно подать заново.
        await db.clear_access_request(CLIENT)

    # Уведомлений ушло не больше лимита, а не по одному на каждое нажатие.
    assert len(tg_bot.chats) <= _request_limiter.limit
    _request_limiter.reset(CLIENT)


async def test_send_rate_stays_under_telegram_limit() -> None:
    """Пауза «каждые N внутри рассылки» не работала: при десятке получателей
    на лид счётчик не успевал дорасти, а лиды складывались в общий поток."""
    import time

    from core.ratelimit import AsyncThrottle

    throttle = AsyncThrottle(rate_per_second=20)
    start = time.perf_counter()
    for _ in range(30):
        await throttle.wait()
    elapsed = time.perf_counter() - start

    assert 30 / elapsed < 30  # ниже потолка Telegram

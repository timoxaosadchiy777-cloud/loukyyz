"""Тесты fan-out: два этапа отбора и экономия вызовов ИИ.

Главное, что здесь проверяется, — сколько раз пайплайн трогает модель:
один анализ и один отклик на лид независимо от числа получателей, и ноль
вызовов, если лид не нужен никому.
"""

from __future__ import annotations

import pytest
import pytest_asyncio

from ai.scoring import LeadScore
from core.fanout import Recipient, prefilter, select
from core.models import LeadState, Order
from core.runtime_config import RuntimeConfig, RuntimeConfigStore
from core.user_settings import UserSettings
from database.db import Database
from main import handle_order, load_recipients

OWNER = 100
ALICE = 201
BOB = 202


def _order(external_id: str = "1", **kwargs) -> Order:
    base = dict(
        source="freelancer",
        external_id=external_id,
        title="Нужен Telegram бот на Python",
        url="https://example.com/1",
        description="Бот приёма заявок с выгрузкой в таблицы",
    )
    base.update(kwargs)
    return Order(**base)


# --- Чистая логика отбора -------------------------------------------------


def _recipient(uid: int, **kwargs) -> Recipient:
    return Recipient(uid, UserSettings(**kwargs))


def test_prefilter_ignores_category_because_ai_has_not_run() -> None:
    """На стадии 1 категории ещё нет — она не должна отсекать никого."""
    picky = _recipient(ALICE, categories=("Telegram-боты",))
    assert prefilter([picky], _order()) == [picky]


def test_prefilter_applies_source_budget_and_keywords() -> None:
    wrong_source = _recipient(1, sources=("upwork",))
    pricey = _recipient(2, min_budget=500)
    other_words = _recipient(3, keywords=("wordpress",))
    fits = _recipient(4, keywords=("telegram",))

    order = _order(budget_value=100)
    assert prefilter([wrong_source, pricey, other_words, fits], order) == [fits]


def test_select_uses_ai_category() -> None:
    matching = _recipient(1, categories=("Telegram-боты",))
    other = _recipient(2, categories=("Дизайн",))
    order = _order(category="Telegram-боты")

    assert select([matching, other], order) == [matching]


def test_select_matches_keyword_via_ai_technology() -> None:
    """Слова нет в тексте, но ИИ распознал стек — лид всё равно подходит."""
    user = _recipient(1, keywords=("aiogram",))
    order = _order(title="Бот для заявок", description="Приём заказов")
    assert select([user], order) == []

    order.technology = "python, aiogram, sqlite"
    assert select([user], order) == [user]


def test_empty_settings_receive_everything() -> None:
    everyone = _recipient(OWNER)
    assert prefilter([everyone], _order()) == [everyone]
    assert select([everyone], _order(category="Что угодно")) == [everyone]


# --- Пайплайн -------------------------------------------------------------


class _FakeScorer:
    """Считает обращения — так видно, что анализ один на лид."""

    def __init__(self, result: LeadScore) -> None:
        self.result = result
        self.calls = 0

    async def score(self, order: Order) -> LeadScore:
        self.calls += 1
        return self.result


class _FakeResponder:
    def __init__(self, text: str = "черновик отклика") -> None:
        self.text = text
        self.calls = 0

    async def generate(self, order: Order, analysis=None) -> str:
        self.calls += 1
        return self.text


class _FakeLLM:
    last_error = None


class _FakeAlerter:
    async def alert(self, text: str, key: str | None = None) -> None:
        pass


class _FakeBot:
    def __init__(self) -> None:
        self.sent: list[tuple[int, str]] = []

    async def send_message(self, chat_id: int, text: str, **kwargs):
        self.sent.append((chat_id, text))


class _Settings:
    owner_id = OWNER
    max_lead_age_hours = 0   # в тестах отсечку по возрасту не применяем


def _score(score: int = 90, **kwargs) -> LeadScore:
    base = dict(
        score=score,
        category="Telegram-боты",
        reason="по профилю",
        probability_of_sale=70,
        should_send=True,
        technology="python, aiogram",
        summary="Бот приёма заявок",
    )
    base.update(kwargs)
    return LeadScore(**base)


@pytest_asyncio.fixture
async def db(tmp_path):
    database = Database(str(tmp_path / "fanout.db"))
    await database.connect()
    try:
        yield database
    finally:
        await database.close()


@pytest.fixture
def config(tmp_path):
    return RuntimeConfigStore(
        tmp_path / "settings.yaml", defaults=RuntimeConfig(min_score=60, min_budget=0)
    )


async def _run(db, config, order, *, scorer=None, responder=None, bot=None):
    scorer = scorer or _FakeScorer(_score())
    responder = responder or _FakeResponder()
    bot = bot or _FakeBot()
    await handle_order(
        order,
        db=db,
        scorer=scorer,
        responder=responder,
        llm=_FakeLLM(),
        bot=bot,
        alerter=_FakeAlerter(),
        settings=_Settings(),
        config=config,
    )
    return scorer, responder, bot


async def test_owner_still_receives_leads(db, config) -> None:
    """Обратная совместимость: владелец без настроек получает всё, как раньше."""
    _, _, bot = await _run(db, config, _order())
    assert [chat for chat, _ in bot.sent] == [OWNER]


async def test_lead_goes_to_every_matching_user(db, config) -> None:
    await db.set_paid_status(ALICE, True)
    await db.set_paid_status(BOB, True)
    await db.save_user_settings(ALICE, UserSettings(keywords=("telegram",)))
    await db.save_user_settings(BOB, UserSettings(keywords=("python",)))

    _, _, bot = await _run(db, config, _order())
    assert sorted(chat for chat, _ in bot.sent) == [OWNER, ALICE, BOB]


async def test_ai_called_once_regardless_of_recipient_count(db, config) -> None:
    """Ключевое требование: один анализ и один отклик на лид, не на человека."""
    for uid in (ALICE, BOB, 203, 204):
        await db.set_paid_status(uid, True)

    scorer, responder, bot = await _run(db, config, _order())

    assert len(bot.sent) == 5  # владелец + четверо
    assert scorer.calls == 1
    assert responder.calls == 1


async def test_no_ai_call_when_lead_suits_nobody(db, config) -> None:
    """Лид, который никому не нужен, не стоит ни одного запроса к модели."""
    await db.save_user_settings(OWNER, UserSettings(keywords=("wordpress",)))

    scorer, responder, bot = await _run(db, config, _order())

    assert scorer.calls == 0
    assert responder.calls == 0
    assert bot.sent == []


async def test_no_response_generated_when_ai_category_suits_nobody(db, config) -> None:
    """Анализ был, но категория никому не подошла — отклик не генерируем."""
    await db.save_user_settings(OWNER, UserSettings(categories=("Дизайн",)))

    scorer, responder, bot = await _run(db, config, _order())

    assert scorer.calls == 1
    assert responder.calls == 0
    assert bot.sent == []


async def test_user_filters_are_applied_individually(db, config) -> None:
    await db.set_paid_status(ALICE, True)
    await db.set_paid_status(BOB, True)
    await db.save_user_settings(OWNER, UserSettings(categories=("Дизайн",)))
    await db.save_user_settings(ALICE, UserSettings(categories=("Telegram-боты",)))
    await db.save_user_settings(BOB, UserSettings(min_budget=1000))

    _, _, bot = await _run(db, config, _order(budget_raw="$100", budget_value=100))

    # Владелец мимо категории, BOB мимо бюджета — остаётся только ALICE.
    assert [chat for chat, _ in bot.sent] == [ALICE]


async def test_rejected_by_score_reaches_nobody(db, config) -> None:
    await db.set_paid_status(ALICE, True)
    scorer = _FakeScorer(_score(score=10))
    responder = _FakeResponder()

    _, _, bot = await _run(db, config, _order(), scorer=scorer, responder=responder)

    assert bot.sent == []
    assert responder.calls == 0


async def test_delivery_is_recorded_for_each_user(db, config) -> None:
    await db.set_paid_status(ALICE, True)
    await _run(db, config, _order())

    order_id = (await db.recent_orders())[0]["id"]
    assert await db.was_delivered(OWNER, order_id) is True
    assert await db.was_delivered(ALICE, order_id) is True
    assert await db.was_delivered(BOB, order_id) is False


async def test_same_lead_is_not_delivered_twice(db, config) -> None:
    """Дедупликация fan-out: повторная рассылка того же заказа никого не будит."""
    from main import deliver

    order = _order()
    _, _, bot = await _run(db, config, order)
    assert len(bot.sent) == 1

    order_id = (await db.recent_orders())[0]["id"]
    again = _FakeBot()
    delivered = await deliver(
        again, db, [Recipient(OWNER, UserSettings())], order, "текст", order_id
    )
    assert delivered == 0
    assert again.sent == []


async def test_personal_response_stored_per_user(db, config) -> None:
    await db.set_paid_status(ALICE, True)
    await _run(db, config, _order(), responder=_FakeResponder("общий черновик"))

    order_id = (await db.recent_orders())[0]["id"]
    # Каждый получил свою копию — правка одного не задевает другого.
    await db.set_delivery_response(ALICE, order_id, "мой вариант")

    assert (await db.get_delivery(ALICE, order_id))["response"] == "мой вариант"
    assert (await db.get_delivery(OWNER, order_id))["response"] == "общий черновик"


async def test_manual_mode_falls_back_to_prefilter(db, config) -> None:
    """ИИ недоступен: категорию проверить нечем, доставляем по стадии 1."""
    await db.save_user_settings(OWNER, UserSettings(categories=("Дизайн",)))
    scorer = _FakeScorer(LeadScore.unknown())

    _, responder, bot = await _run(db, config, _order(), scorer=scorer)

    assert [chat for chat, _ in bot.sent] == [OWNER]
    assert responder.calls == 0  # отклик в ручном режиме не генерируем


async def test_disabled_source_skips_everything(db, config) -> None:
    """Биржа выключена в sources_settings — лид с неё до ИИ не доходит."""
    await db.set_paid_status(ALICE, True)
    for uid in (OWNER, ALICE):
        await db.set_source_enabled(uid, "freelancer", False)

    scorer, _, bot = await _run(db, config, _order(source="freelancer"))
    assert scorer.calls == 0
    assert bot.sent == []


async def test_blocked_user_does_not_break_delivery(db, config) -> None:
    """Один получатель заблокировал бота — остальные всё равно получают лид."""

    class _FlakyBot(_FakeBot):
        async def send_message(self, chat_id: int, text: str, **kwargs):
            if chat_id == OWNER:
                raise RuntimeError("bot was blocked by the user")
            await super().send_message(chat_id, text, **kwargs)

    await db.set_paid_status(ALICE, True)
    _, _, bot = await _run(db, config, _order(), bot=_FlakyBot())

    assert [chat for chat, _ in bot.sent] == [ALICE]


# --- Получатели -----------------------------------------------------------


async def test_owner_is_first_and_not_duplicated(db) -> None:
    await db.set_paid_status(OWNER, True)
    await db.set_paid_status(ALICE, True)

    recipients = await load_recipients(db, OWNER)
    assert [r.telegram_id for r in recipients] == [OWNER, ALICE]


async def test_recipients_exclude_users_without_access(db) -> None:
    await db.set_paid_status(ALICE, True)
    await db.register_user(BOB, "bob")  # зарегистрирован, но без доступа

    recipients = await load_recipients(db, OWNER)
    assert [r.telegram_id for r in recipients] == [OWNER, ALICE]


async def test_revoked_user_stops_receiving(db, config) -> None:
    await db.set_paid_status(ALICE, True)
    await db.set_paid_status(ALICE, False)

    _, _, bot = await _run(db, config, _order())
    assert [chat for chat, _ in bot.sent] == [OWNER]


async def test_recipients_carry_their_own_settings(db) -> None:
    await db.set_paid_status(ALICE, True)
    await db.save_user_settings(ALICE, UserSettings(min_budget=300))

    recipients = await load_recipients(db, OWNER)
    by_id = {r.telegram_id: r.settings for r in recipients}
    assert by_id[ALICE].min_budget == 300
    assert by_id[OWNER].min_budget == 0


async def test_no_recipients_at_all(db, config) -> None:
    class _NoOwner:
        owner_id = 0
        max_lead_age_hours = 0

    order = _order()
    await handle_order(
        order,
        db=db,
        scorer=_FakeScorer(_score()),
        responder=_FakeResponder(),
        llm=_FakeLLM(),
        bot=_FakeBot(),
        alerter=_FakeAlerter(),
        settings=_NoOwner(),
        config=config,
    )
    assert await db.recent_orders() == []  # сохранён как filtered, не как new


# --- Личное состояние лида ------------------------------------------------


async def test_states_are_independent_between_users(db, config) -> None:
    await db.set_paid_status(ALICE, True)
    await _run(db, config, _order())
    order_id = (await db.recent_orders())[0]["id"]

    await db.set_delivery_state(OWNER, order_id, LeadState.SAVED)
    await db.set_delivery_state(ALICE, order_id, LeadState.REJECTED)

    assert await db.is_lead_saved(OWNER, order_id) is True
    assert await db.is_lead_saved(ALICE, order_id) is False
    assert (await db.get_delivery(ALICE, order_id))["state"] == LeadState.REJECTED


async def test_crm_status_is_per_user(db, config) -> None:
    """Иначе один пользователь переводит лид в «Выиграл» — и это видят все."""
    await db.set_paid_status(ALICE, True)
    await _run(db, config, _order())
    order_id = (await db.recent_orders())[0]["id"]

    await db.set_delivery_crm(OWNER, order_id, "won")
    assert (await db.get_delivery(OWNER, order_id))["crm_status"] == "won"
    assert (await db.get_delivery(ALICE, order_id))["crm_status"] == "new"

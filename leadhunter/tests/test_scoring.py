"""Тесты AI Lead Scoring: разбор JSON и поведение при сбоях (через фейковый LLM)."""

from __future__ import annotations

from ai.scoring import LeadScore, ScoringService, _parse_score
from core.models import Order
from core.profile import ProfileLoader


def _service(reply):
    return ScoringService(_FakeLLM(reply), ProfileLoader("does-not-exist.md"))


def _order() -> Order:
    return Order(
        source="rss",
        external_id="1",
        title="Нужен Telegram бот",
        url="https://example.com/1",
        description="Бот приёма заявок с оплатой",
    )


class _FakeLLM:
    """LLM-заглушка: отдаёт заранее заданный ответ и запоминает json_mode."""

    def __init__(self, reply: str | None) -> None:
        self._reply = reply
        self.json_mode: bool | None = None

    async def complete(self, *, system, user, max_output_tokens, temperature, json_mode=False, label="llm"):
        self.json_mode = json_mode
        return self._reply

    async def aclose(self) -> None:
        return None


def test_parse_clean_json() -> None:
    score = _parse_score(
        '{"score": 93, "category": "Telegram Bot", "reason": "по профилю",'
        ' "probability_of_sale": 70, "should_send": true}'
    )
    assert score is not None
    assert score.score == 93
    assert score.category == "Telegram Bot"
    assert score.reason == "по профилю"
    assert score.probability_of_sale == 70
    assert score.should_send is True
    assert score.available is True


def test_probability_defaults_to_score_when_missing() -> None:
    score = _parse_score('{"score": 88, "category": "x", "reason": "y", "should_send": true}')
    assert score is not None
    assert score.probability_of_sale == 88  # нет поля → приближаем через score


def test_parse_fenced_json() -> None:
    raw = "```json\n{\"score\": 80, \"category\": \"Автоматизация\", \"reason\": \"ok\", \"should_send\": true}\n```"
    score = _parse_score(raw)
    assert score is not None
    assert score.score == 80
    assert score.category == "Автоматизация"


def test_parse_json_with_surrounding_prose() -> None:
    raw = 'Вот оценка: {"score": 5, "category": "Дизайн", "reason": "не профиль", "should_send": false} — готово.'
    score = _parse_score(raw)
    assert score is not None
    assert score.score == 5
    assert score.should_send is False


def test_parse_clamps_and_defaults_should_send() -> None:
    # score вне диапазона зажимается; отсутствие should_send выводится из score.
    high = _parse_score('{"score": 150, "category": "x", "reason": "y"}')
    assert high is not None and high.score == 100 and high.should_send is True
    low = _parse_score('{"score": -20, "category": "x", "reason": "y"}')
    assert low is not None and low.score == 0 and low.should_send is False


def test_parse_bool_variants() -> None:
    assert _parse_score('{"score": 70, "should_send": "да"}').should_send is True
    assert _parse_score('{"score": 70, "should_send": "no"}').should_send is False
    assert _parse_score('{"score": 70, "should_send": 1}').should_send is True


def test_parse_invalid() -> None:
    assert _parse_score("no json here") is None
    assert _parse_score('{"category": "x"}') is None  # нет score
    assert _parse_score('{"score": "abc"}') is None  # score не число
    assert _parse_score("[1, 2, 3]") is None  # не объект


async def test_service_returns_leadscore() -> None:
    service = _service(
        '{"score": 90, "category": "Парсинг", "reason": "по профилю",'
        ' "probability_of_sale": 65, "should_send": true}'
    )
    score = await service.score(_order())
    assert score.available is True
    assert score.score == 90
    assert score.probability_of_sale == 65
    assert service._llm.json_mode is True  # скоринг просит строгий JSON


async def test_service_unknown_when_llm_unavailable() -> None:
    service = _service(None)
    score = await service.score(_order())
    assert score.available is False
    assert score.score is None


async def test_service_unknown_on_garbage() -> None:
    service = _service("совсем не json")
    score = await service.score(_order())
    assert score.available is False


def test_leadscore_unknown_helper() -> None:
    score = LeadScore.unknown()
    assert score.available is False
    assert score.score is None
    assert score.should_send is None

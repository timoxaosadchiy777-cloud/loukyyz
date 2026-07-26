"""Тесты решающего слоя пайплайна: _decide и _apply_score."""

from __future__ import annotations

from ai.scoring import LeadScore
from core.decision import apply_score, decide
from core.models import Order


def _score(score, should_send, *, category="Bot", reason="r", probability=50) -> LeadScore:
    return LeadScore(
        score=score,
        category=category,
        reason=reason,
        probability_of_sale=probability,
        should_send=should_send,
    )


def test_decide_passes_when_recommended_and_above_threshold() -> None:
    assert decide(_score(90, True), min_score=60) is True


def test_decide_rejects_below_threshold() -> None:
    assert decide(_score(40, True), min_score=60) is False


def test_decide_veto_overrides_high_score() -> None:
    # should_send=false отклоняет заказ даже при высоком score.
    assert decide(_score(95, False), min_score=60) is False


def test_decide_none_when_unavailable() -> None:
    assert decide(LeadScore.unknown(), min_score=60) is None


def test_decide_boundary_inclusive() -> None:
    assert decide(_score(60, True), min_score=60) is True


def test_apply_score_copies_fields() -> None:
    order = Order(source="rss", external_id="1", title="t", url="u", description="d")
    apply_score(order, _score(77, True, category="Парсинг", reason="по профилю", probability=65))
    assert order.score == 77
    assert order.category == "Парсинг"
    assert order.reason == "по профилю"
    assert order.probability_of_sale == 65
    assert order.should_send is True


def test_apply_unknown_score() -> None:
    order = Order(source="rss", external_id="1", title="t", url="u", description="d")
    apply_score(order, LeadScore.unknown())
    assert order.score is None
    assert order.probability_of_sale is None
    assert order.should_send is None

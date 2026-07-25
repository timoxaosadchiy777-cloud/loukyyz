"""Тесты решающего слоя пайплайна: _decide и _apply_score."""

from __future__ import annotations

from ai.scoring import LeadScore
from core.decision import apply_score, decide
from core.models import Order


def test_decide_passes_when_recommended_and_above_threshold() -> None:
    score = LeadScore(score=90, category="Bot", reason="ok", should_send=True)
    assert decide(score, min_score=60) is True


def test_decide_rejects_below_threshold() -> None:
    score = LeadScore(score=40, category="Bot", reason="слабо", should_send=True)
    assert decide(score, min_score=60) is False


def test_decide_veto_overrides_high_score() -> None:
    # should_send=false отклоняет заказ даже при высоком score.
    score = LeadScore(score=95, category="Bot", reason="не подходит", should_send=False)
    assert decide(score, min_score=60) is False


def test_decide_none_when_unavailable() -> None:
    assert decide(LeadScore.unknown(), min_score=60) is None


def test_decide_boundary_inclusive() -> None:
    score = LeadScore(score=60, category="x", reason="y", should_send=True)
    assert decide(score, min_score=60) is True


def test_apply_score_copies_fields() -> None:
    order = Order(source="rss", external_id="1", title="t", url="u", description="d")
    score = LeadScore(score=77, category="Парсинг", reason="по профилю", should_send=True)
    apply_score(order, score)
    assert order.score == 77
    assert order.category == "Парсинг"
    assert order.reason == "по профилю"
    assert order.should_send is True


def test_apply_unknown_score() -> None:
    order = Order(source="rss", external_id="1", title="t", url="u", description="d")
    apply_score(order, LeadScore.unknown())
    assert order.score is None
    assert order.should_send is None

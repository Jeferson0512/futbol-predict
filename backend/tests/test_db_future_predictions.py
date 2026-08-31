from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from futpredict.domain.fixtures import Fixture
from futpredict.evaluation import db_future_predictions


def _fixture(match_id: int | None, kickoff: datetime) -> Fixture:
    return Fixture(
        match_id=match_id,
        kickoff_utc=kickoff,
        season="2627",
        division="E0",
        home_team="Arsenal",
        away_team="Chelsea",
        avg_home_odds=2.1,
        avg_draw_odds=3.4,
        avg_away_odds=3.5,
        odds_source="avg",
    )


def test_freeze_future_predictions_returns_empty_without_eligible(monkeypatch: Any) -> None:
    frozen_at = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)
    # Un fixture ya empezado (kickoff <= frozen_at) y otro sin match_id: ambos inelegibles.
    fixtures = [
        _fixture(match_id=1, kickoff=frozen_at - timedelta(hours=1)),
        _fixture(match_id=None, kickoff=frozen_at + timedelta(days=1)),
    ]
    monkeypatch.setattr(
        db_future_predictions,
        "load_upcoming_fixtures_from_db",
        lambda *args, **kwargs: fixtures,
    )

    def _fail_training(*_args: Any, **_kwargs: Any) -> list[Any]:
        raise AssertionError("no debe cargar entrenamiento sin fixtures elegibles")

    monkeypatch.setattr(
        db_future_predictions,
        "load_finished_match_results_before_from_db",
        _fail_training,
    )

    summary = db_future_predictions.freeze_future_predictions(
        object(),  # type: ignore[arg-type]
        frozen_at=frozen_at,
    )

    assert summary.fixtures == 2
    assert summary.eligible_fixtures == 0
    assert summary.candidates == 0
    assert summary.inserted_predictions == 0
    assert summary.frozen_at == frozen_at

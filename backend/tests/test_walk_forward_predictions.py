from __future__ import annotations

from datetime import UTC, datetime

from futpredict.domain.matches import MatchResult
from futpredict.evaluation.walk_forward_predictions import (
    run_expanding_walk_forward_predictions,
)


def test_expanding_walk_forward_predictions_keep_only_evaluation_rows() -> None:
    predictions = run_expanding_walk_forward_predictions(
        [
            _match(1, "2021", 1, 2, 1),
            _match(2, "2122", 2, 1, 1),
            _match(3, "2223", 3, 0, 1),
        ],
        start_season="2021",
        end_season="2223",
        initial_train_seasons=2,
    )

    assert {prediction.evaluation_season for prediction in predictions} == {"2223"}
    assert {prediction.prediction.match.match_id for prediction in predictions} == {3}
    assert {prediction.prediction.model for prediction in predictions} == {
        "always_home",
        "historical_frequency",
        "elo_simple",
    }


def _match(
    match_id: int,
    season: str,
    month: int,
    home_goals: int,
    away_goals: int,
) -> MatchResult:
    outcome = "H" if home_goals > away_goals else "D" if home_goals == away_goals else "A"
    return MatchResult(
        kickoff_utc=datetime(2020 + month, month, 1, tzinfo=UTC),
        season=season,
        division="E0",
        home_team=f"Home {month}",
        away_team=f"Away {month}",
        home_goals=home_goals,
        away_goals=away_goals,
        outcome=outcome,
        match_id=match_id,
    )

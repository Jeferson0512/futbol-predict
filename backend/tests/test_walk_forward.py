from __future__ import annotations

from datetime import UTC, datetime

import pytest

from futpredict.domain.matches import MatchResult
from futpredict.evaluation.backtest import PredictionRow
from futpredict.evaluation.walk_forward import (
    run_expanding_walk_forward,
    summarize_walk_forward_metrics,
)


def test_expanding_walk_forward_creates_one_evaluation_window_per_season_after_training() -> None:
    metrics = run_expanding_walk_forward(
        [
            _match("2021", 1, 1, 2, 1),
            _match("2122", 2, 1, 1, 1),
            _match("2223", 3, 1, 0, 1),
            _match("2324", 4, 1, 3, 0),
        ],
        start_season="2021",
        end_season="2324",
        initial_train_seasons=2,
    )

    windows = {
        (
            metric.division,
            metric.evaluation_season,
            metric.train_start_season,
            metric.train_end_season,
        )
        for metric in metrics
    }
    overall = summarize_walk_forward_metrics(metrics)

    assert windows == {
        ("E0", "2223", "2021", "2122"),
        ("E0", "2324", "2021", "2223"),
    }
    assert {metric.summary.model for metric in metrics} == {
        "always_home",
        "historical_frequency",
        "elo_simple",
    }
    assert all(summary.n_matches == 2 for summary in overall)


def test_expanding_walk_forward_requires_evaluation_season() -> None:
    with pytest.raises(ValueError, match="at least one evaluation season"):
        run_expanding_walk_forward(
            [_match("2021", 1, 1, 2, 1), _match("2122", 2, 1, 1, 1)],
            start_season="2021",
            end_season="2122",
            initial_train_seasons=2,
        )


def test_expanding_walk_forward_includes_extra_prediction_provider() -> None:
    metrics = run_expanding_walk_forward(
        [
            _match("2021", 1, 1, 2, 1),
            _match("2122", 2, 1, 1, 1),
            _match("2223", 3, 1, 0, 1),
        ],
        start_season="2021",
        end_season="2223",
        initial_train_seasons=2,
        extra_prediction_providers=(
            lambda match: PredictionRow("external_model", match, (0.4, 0.3, 0.3)),
        ),
    )

    external_metrics = [metric for metric in metrics if metric.summary.model == "external_model"]

    assert len(external_metrics) == 1
    assert external_metrics[0].evaluation_season == "2223"
    assert external_metrics[0].summary.n_matches == 1


def _match(
    season: str,
    month: int,
    day: int,
    home_goals: int,
    away_goals: int,
) -> MatchResult:
    outcome = "H" if home_goals > away_goals else "D" if home_goals == away_goals else "A"
    return MatchResult(
        kickoff_utc=datetime(2020 + month, month, day, tzinfo=UTC),
        season=season,
        division="E0",
        home_team=f"Home {month}",
        away_team=f"Away {month}",
        home_goals=home_goals,
        away_goals=away_goals,
        outcome=outcome,
    )

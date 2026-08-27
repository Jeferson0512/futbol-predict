from __future__ import annotations

from datetime import UTC, datetime

from futpredict.domain.fixtures import Fixture
from futpredict.domain.matches import MatchResult
from futpredict.evaluation.future_predictions import build_fixture_predictions


def test_build_fixture_predictions_returns_available_models() -> None:
    fixture = Fixture(
        match_id=10,
        kickoff_utc=datetime(2026, 8, 30, 14, 0, tzinfo=UTC),
        season="2627",
        division="E0",
        home_team="Arsenal",
        away_team="Chelsea",
        avg_home_odds=2.1,
        avg_draw_odds=3.5,
        avg_away_odds=3.4,
        odds_source="avg",
    )
    predictions = build_fixture_predictions(
        [fixture],
        [
            _match("Arsenal", "Chelsea", 2, 0),
            _match("Chelsea", "Arsenal", 1, 1),
        ],
    )

    assert {prediction.model for prediction in predictions} == {
        "always_home",
        "historical_frequency",
        "elo_simple",
        "market_avg_odds",
    }
    market = next(prediction for prediction in predictions if prediction.model == "market_avg_odds")
    assert round(sum(market.probabilities), 6) == 1
    assert market.train_window_start_utc is not None


def test_build_fixture_predictions_skips_market_without_odds() -> None:
    fixture = Fixture(
        match_id=10,
        kickoff_utc=datetime(2026, 8, 30, 14, 0, tzinfo=UTC),
        season="2627",
        division="E0",
        home_team="Arsenal",
        away_team="Chelsea",
    )
    predictions = build_fixture_predictions([fixture], [])

    assert {prediction.model for prediction in predictions} == {
        "always_home",
        "historical_frequency",
        "elo_simple",
    }


def _match(
    home_team: str,
    away_team: str,
    home_goals: int,
    away_goals: int,
) -> MatchResult:
    outcome = "H" if home_goals > away_goals else "D" if home_goals == away_goals else "A"
    return MatchResult(
        kickoff_utc=datetime(2025, 8, 15, 14, 0, tzinfo=UTC),
        season="2526",
        division="E0",
        home_team=home_team,
        away_team=away_team,
        home_goals=home_goals,
        away_goals=away_goals,
        outcome=outcome,
    )

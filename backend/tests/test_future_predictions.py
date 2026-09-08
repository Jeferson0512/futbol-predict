from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest import mock

import numpy as np

from futpredict.domain.fixtures import Fixture
from futpredict.domain.matches import MatchResult, result_from_goals
from futpredict.evaluation import future_predictions
from futpredict.evaluation.future_predictions import build_fixture_predictions
from futpredict.models.poisson import DIXON_COLES_MODEL_NAME


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


def test_dixon_coles_appears_with_enough_history() -> None:
    fixture = Fixture(
        match_id=99,
        kickoff_utc=datetime(2026, 8, 30, 14, 0, tzinfo=UTC),
        season="2627",
        division="E0",
        home_team="Alpha",
        away_team="Beta",
    )

    predictions = build_fixture_predictions([fixture], _league_history())

    by_model = {prediction.model: prediction for prediction in predictions}
    assert DIXON_COLES_MODEL_NAME in by_model
    probabilities = by_model[DIXON_COLES_MODEL_NAME].probabilities
    assert round(sum(probabilities), 6) == 1
    assert by_model[DIXON_COLES_MODEL_NAME].algorithm == "dixon_coles"


def test_dixon_coles_skipped_without_enough_history() -> None:
    fixture = Fixture(
        match_id=10,
        kickoff_utc=datetime(2026, 8, 30, 14, 0, tzinfo=UTC),
        season="2627",
        division="E0",
        home_team="Arsenal",
        away_team="Chelsea",
    )

    predictions = build_fixture_predictions(
        [fixture],
        [_match("Arsenal", "Chelsea", 2, 0)],
    )

    # Con un solo partido no hay con que ajustar: se omite en vez de inventar.
    assert DIXON_COLES_MODEL_NAME not in {prediction.model for prediction in predictions}


def test_dixon_coles_skipped_for_unseen_team() -> None:
    fixture = Fixture(
        match_id=99,
        kickoff_utc=datetime(2026, 8, 30, 14, 0, tzinfo=UTC),
        season="2627",
        division="E0",
        home_team="Recien Ascendido",
        away_team="Beta",
    )

    predictions = build_fixture_predictions([fixture], _league_history())

    assert DIXON_COLES_MODEL_NAME not in {prediction.model for prediction in predictions}
    # Los demas modelos si deben responder: solo cae el que no puede.
    assert "elo_simple" in {prediction.model for prediction in predictions}


def test_dixon_coles_is_not_fitted_when_not_requested() -> None:
    """El ajuste cuesta decimas de segundo y esto corre en cada request del API."""
    fixture = Fixture(
        match_id=99,
        kickoff_utc=datetime(2026, 8, 30, 14, 0, tzinfo=UTC),
        season="2627",
        division="E0",
        home_team="Alpha",
        away_team="Beta",
    )

    with mock.patch.object(
        future_predictions.DixonColesMatchModel,
        "fit",
        side_effect=AssertionError("no se debe ajustar si no se pide"),
    ):
        predictions = build_fixture_predictions(
            [fixture],
            _league_history(),
            model_names=["elo_simple"],
        )

    assert [prediction.model for prediction in predictions] == ["elo_simple"]


def _league_history() -> list[MatchResult]:
    """Historia sintetica suficiente para ajustar Dixon-Coles (>= 50 partidos)."""
    teams = ("Alpha", "Beta", "Gamma", "Delta", "Epsilon", "Zeta", "Eta", "Theta")
    rng = np.random.default_rng(20260908)
    strength = {team: (len(teams) - 1 - index) * 0.3 for index, team in enumerate(teams)}
    matches: list[MatchResult] = []
    day = 0
    for home in teams:
        for away in teams:
            if home == away:
                continue
            edge = strength[home] - strength[away]
            home_goals = int(rng.poisson(max(0.15, 1.4 + 0.45 * edge)))
            away_goals = int(rng.poisson(max(0.15, 1.1 - 0.45 * edge)))
            matches.append(
                MatchResult(
                    kickoff_utc=datetime(2025, 8, 15, 14, 0, tzinfo=UTC) + timedelta(days=day),
                    season="2526",
                    division="E0",
                    home_team=home,
                    away_team=away,
                    home_goals=home_goals,
                    away_goals=away_goals,
                    outcome=result_from_goals(home_goals, away_goals),
                )
            )
            day += 1
    return matches


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

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from futpredict.domain.fixtures import Fixture
from futpredict.domain.matches import MatchResult
from futpredict.evaluation.backtest import market_probabilities
from futpredict.evaluation.db_walk_forward import (
    ALGORITHM_BY_MODEL,
    WALK_FORWARD_FEATURE_SET_VERSION,
)
from futpredict.models.baseline import always_home_probabilities, historical_frequency_probabilities
from futpredict.models.elo import EloConfig, expected_home_score, update_elo
from futpredict.models.poisson import (
    DIXON_COLES_MODEL_NAME,
    MIN_TRAIN_MATCHES,
    DixonColesMatchModel,
    goal_samples_from_matches,
)

SUPPORTED_FUTURE_MODELS = (
    "market_avg_odds",
    DIXON_COLES_MODEL_NAME,
    "elo_simple",
    "historical_frequency",
    "always_home",
)


@dataclass(frozen=True)
class FixturePrediction:
    fixture: Fixture
    model: str
    algorithm: str
    feature_set_version: str
    probabilities: tuple[float, float, float]
    train_window_start_utc: datetime | None
    train_window_end_utc: datetime | None


@dataclass
class _PredictionState:
    result_counts: dict[str, list[int]]
    ratings: dict[tuple[str, str], float]
    train_windows: dict[str, tuple[datetime, datetime]]
    matches_by_division: dict[str, list[MatchResult]]
    # Dixon-Coles se ajusta por division y solo cuando hace falta: el ajuste
    # cuesta decimas de segundo y este codigo corre en cada request del API.
    # `None` marca una division con datos insuficientes, para no reintentar.
    goal_models: dict[str, DixonColesMatchModel | None]


def build_fixture_predictions(
    fixtures: list[Fixture],
    training_matches: list[MatchResult],
    *,
    model_names: list[str] | None = None,
    elo_config: EloConfig | None = None,
    initial_rating: float = 1500.0,
) -> list[FixturePrediction]:
    selected_models = model_names or list(SUPPORTED_FUTURE_MODELS)
    unsupported = sorted(set(selected_models) - set(SUPPORTED_FUTURE_MODELS))
    if unsupported:
        msg = f"unsupported future prediction models: {', '.join(unsupported)}"
        raise ValueError(msg)

    cfg = elo_config or EloConfig()
    state = _build_prediction_state(training_matches, cfg, initial_rating)
    predictions: list[FixturePrediction] = []

    for fixture in sorted(fixtures, key=lambda item: item.kickoff_utc):
        train_window = state.train_windows.get(fixture.division)
        for model_name in selected_models:
            probabilities = _probabilities_for_model(
                fixture,
                model_name=model_name,
                state=state,
                elo_config=cfg,
                initial_rating=initial_rating,
            )
            if probabilities is None:
                continue
            predictions.append(
                FixturePrediction(
                    fixture=fixture,
                    model=model_name,
                    algorithm=ALGORITHM_BY_MODEL[model_name],
                    feature_set_version=WALK_FORWARD_FEATURE_SET_VERSION,
                    probabilities=probabilities,
                    train_window_start_utc=train_window[0] if train_window is not None else None,
                    train_window_end_utc=train_window[1] if train_window is not None else None,
                )
            )

    return predictions


def _build_prediction_state(
    training_matches: list[MatchResult],
    elo_config: EloConfig,
    initial_rating: float,
) -> _PredictionState:
    result_counts: dict[str, list[int]] = {}
    ratings: dict[tuple[str, str], float] = {}
    train_windows: dict[str, tuple[datetime, datetime]] = {}
    matches_by_division: dict[str, list[MatchResult]] = {}

    for match in sorted(training_matches, key=lambda item: item.kickoff_utc):
        group = match.division
        matches_by_division.setdefault(group, []).append(match)
        counts = result_counts.setdefault(group, [0, 0, 0])
        if match.outcome == "H":
            counts[0] += 1
        elif match.outcome == "D":
            counts[1] += 1
        else:
            counts[2] += 1

        home_key = (group, match.home_team)
        away_key = (group, match.away_team)
        home_rating = ratings.get(home_key, initial_rating)
        away_rating = ratings.get(away_key, initial_rating)
        new_home, new_away = update_elo(
            home_rating,
            away_rating,
            match.home_goals,
            match.away_goals,
            elo_config,
        )
        ratings[home_key] = new_home
        ratings[away_key] = new_away

        current_window = train_windows.get(group)
        if current_window is None:
            train_windows[group] = (match.kickoff_utc, match.kickoff_utc)
        else:
            train_windows[group] = (current_window[0], match.kickoff_utc)

    return _PredictionState(
        result_counts=result_counts,
        ratings=ratings,
        train_windows=train_windows,
        matches_by_division=matches_by_division,
        goal_models={},
    )


def _goal_model_for_division(
    state: _PredictionState,
    division: str,
) -> DixonColesMatchModel | None:
    """Ajusta Dixon-Coles para una division la primera vez que se pide."""
    if division in state.goal_models:
        return state.goal_models[division]

    samples = goal_samples_from_matches(state.matches_by_division.get(division, []))
    if len(samples) < MIN_TRAIN_MATCHES:
        state.goal_models[division] = None
        return None
    model = DixonColesMatchModel().fit(samples)
    state.goal_models[division] = model
    return model


def _probabilities_for_model(
    fixture: Fixture,
    *,
    model_name: str,
    state: _PredictionState,
    elo_config: EloConfig,
    initial_rating: float,
) -> tuple[float, float, float] | None:
    if model_name == "always_home":
        return always_home_probabilities()
    if model_name == "historical_frequency":
        counts = state.result_counts.get(fixture.division, [0, 0, 0])
        return historical_frequency_probabilities(counts[0], counts[1], counts[2])
    if model_name == DIXON_COLES_MODEL_NAME:
        model = _goal_model_for_division(state, fixture.division)
        if model is None:
            return None
        return model.predict_proba(fixture.home_team, fixture.away_team)
    if model_name == "market_avg_odds":
        return market_probabilities(_fixture_as_market_match(fixture))
    if model_name == "elo_simple":
        home_rating = state.ratings.get((fixture.division, fixture.home_team), initial_rating)
        away_rating = state.ratings.get((fixture.division, fixture.away_team), initial_rating)
        home_expected = expected_home_score(
            home_rating,
            away_rating,
            elo_config.home_advantage,
        )
        draw_probability = 0.26
        decisive_probability = 1.0 - draw_probability
        return (
            home_expected * decisive_probability,
            draw_probability,
            (1.0 - home_expected) * decisive_probability,
        )

    msg = f"unsupported future prediction model: {model_name}"
    raise ValueError(msg)


def _fixture_as_market_match(fixture: Fixture) -> MatchResult:
    return MatchResult(
        kickoff_utc=fixture.kickoff_utc,
        season=fixture.season,
        division=fixture.division,
        home_team=fixture.home_team,
        away_team=fixture.away_team,
        home_goals=0,
        away_goals=0,
        outcome="D",
        avg_home_odds=fixture.avg_home_odds,
        avg_draw_odds=fixture.avg_draw_odds,
        avg_away_odds=fixture.avg_away_odds,
        odds_source=fixture.odds_source,
        match_id=fixture.match_id,
    )

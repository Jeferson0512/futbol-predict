"""Walk-forward temporal para modelos de goles (Dixon-Coles).

Paralelo a `run_ml_walk_forward`, pero el modelo no come features rodantes sino
marcadores: entrena con los partidos de las temporadas previas y predice la de
evaluacion. Mantiene el mismo anti-leakage (nunca entrena con la temporada que
evalua) y produce los mismos `WalkForwardMetric`, asi que persiste y compite por
campeon igual que los baselines.

Acepta `seasons` explicito para las ligas que van por ano calendario (Peru,
Brasil, Argentina), igual que `run_expanding_walk_forward`.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass

from futpredict.data.football_data_uk_catalog import season_range
from futpredict.domain.matches import MatchResult
from futpredict.evaluation.backtest import PredictionRow, summarize_predictions
from futpredict.evaluation.walk_forward import (
    DEFAULT_INITIAL_TRAIN_SEASONS,
    WalkForwardMetric,
)
from futpredict.evaluation.walk_forward_predictions import WalkForwardPrediction
from futpredict.models.poisson import (
    DIXON_COLES_MODEL_NAME,
    MIN_TRAIN_MATCHES,
    DixonColesMatchModel,
    goal_samples_from_matches,
)

GoalModelFactory = Callable[[], DixonColesMatchModel]

DEFAULT_GOAL_MODELS: tuple[tuple[GoalModelFactory, str], ...] = (
    (DixonColesMatchModel, DIXON_COLES_MODEL_NAME),
)


@dataclass(frozen=True)
class _Window:
    """Una ventana temporal ya resuelta: con que entrenar y que evaluar."""

    division: str
    evaluation_season: str
    train_start_season: str
    train_end_season: str
    train_matches: list[MatchResult]
    eval_matches: list[MatchResult]


def _windows(
    matches: Sequence[MatchResult],
    *,
    start_season: str,
    end_season: str,
    initial_train_seasons: int,
    seasons: Sequence[str] | None,
    min_train_matches: int,
) -> Iterator[_Window]:
    """Recorre las ventanas walk-forward comunes a metricas y predicciones."""
    season_list = list(seasons) if seasons is not None else season_range(start_season, end_season)
    if initial_train_seasons < 1:
        msg = "initial_train_seasons must be positive"
        raise ValueError(msg)
    if len(season_list) <= initial_train_seasons:
        msg = "season range must leave at least one evaluation season"
        raise ValueError(msg)

    season_set = set(season_list)
    by_division: dict[str, list[MatchResult]] = {}
    for match in matches:
        if match.season in season_set:
            by_division.setdefault(match.division, []).append(match)

    for division, division_matches in sorted(by_division.items()):
        ordered = sorted(division_matches, key=lambda match: match.kickoff_utc)
        for eval_index in range(initial_train_seasons, len(season_list)):
            train_seasons = set(season_list[:eval_index])
            eval_season = season_list[eval_index]
            train_matches = [match for match in ordered if match.season in train_seasons]
            eval_matches = [match for match in ordered if match.season == eval_season]
            if not train_matches or not eval_matches:
                continue
            if len(goal_samples_from_matches(train_matches)) < min_train_matches:
                continue
            yield _Window(
                division=division,
                evaluation_season=eval_season,
                train_start_season=season_list[0],
                train_end_season=season_list[eval_index - 1],
                train_matches=train_matches,
                eval_matches=eval_matches,
            )


def run_goal_model_walk_forward(
    matches: Sequence[MatchResult],
    *,
    start_season: str,
    end_season: str,
    initial_train_seasons: int = DEFAULT_INITIAL_TRAIN_SEASONS,
    seasons: Sequence[str] | None = None,
    min_train_matches: int = MIN_TRAIN_MATCHES,
    model_factory: GoalModelFactory = DixonColesMatchModel,
    model_name: str = DIXON_COLES_MODEL_NAME,
) -> list[WalkForwardMetric]:
    metrics: list[WalkForwardMetric] = []
    for window in _windows(
        matches,
        start_season=start_season,
        end_season=end_season,
        initial_train_seasons=initial_train_seasons,
        seasons=seasons,
        min_train_matches=min_train_matches,
    ):
        rows = _fit_and_predict(window, model_factory, model_name)
        if not rows:
            continue
        for summary in summarize_predictions(rows):
            metrics.append(
                WalkForwardMetric(
                    division=window.division,
                    evaluation_season=window.evaluation_season,
                    train_start_season=window.train_start_season,
                    train_end_season=window.train_end_season,
                    train_window_start_utc=window.train_matches[0].kickoff_utc,
                    train_window_end_utc=window.train_matches[-1].kickoff_utc,
                    eval_window_start_utc=window.eval_matches[0].kickoff_utc,
                    eval_window_end_utc=window.eval_matches[-1].kickoff_utc,
                    summary=summary,
                )
            )
    return metrics


def run_goal_model_walk_forward_predictions(
    matches: Sequence[MatchResult],
    *,
    start_season: str,
    end_season: str,
    initial_train_seasons: int = DEFAULT_INITIAL_TRAIN_SEASONS,
    seasons: Sequence[str] | None = None,
    min_train_matches: int = MIN_TRAIN_MATCHES,
    model_factory: GoalModelFactory = DixonColesMatchModel,
    model_name: str = DIXON_COLES_MODEL_NAME,
) -> list[WalkForwardPrediction]:
    """Predicciones congelables por partido, para el historial de la app.

    Mismo recorrido que las metricas, pero devuelve fila por partido en vez de
    agregados: es lo que alimenta la vista Resultados (acierto/fallo).
    """
    predictions: list[WalkForwardPrediction] = []
    for window in _windows(
        matches,
        start_season=start_season,
        end_season=end_season,
        initial_train_seasons=initial_train_seasons,
        seasons=seasons,
        min_train_matches=min_train_matches,
    ):
        for row in _fit_and_predict(window, model_factory, model_name):
            predictions.append(
                WalkForwardPrediction(
                    division=window.division,
                    evaluation_season=window.evaluation_season,
                    train_start_season=window.train_start_season,
                    train_end_season=window.train_end_season,
                    train_window_start_utc=window.train_matches[0].kickoff_utc,
                    train_window_end_utc=window.train_matches[-1].kickoff_utc,
                    eval_window_start_utc=window.eval_matches[0].kickoff_utc,
                    eval_window_end_utc=window.eval_matches[-1].kickoff_utc,
                    prediction=row,
                )
            )
    return predictions


def _fit_and_predict(
    window: _Window,
    model_factory: GoalModelFactory,
    model_name: str,
) -> list[PredictionRow]:
    model = model_factory().fit(goal_samples_from_matches(window.train_matches))
    return _predict_rows(model, window.eval_matches, model_name)


def run_configured_goal_walk_forward(
    matches: Sequence[MatchResult],
    *,
    start_season: str,
    end_season: str,
    initial_train_seasons: int = DEFAULT_INITIAL_TRAIN_SEASONS,
    seasons: Sequence[str] | None = None,
    models: Sequence[tuple[GoalModelFactory, str]] = DEFAULT_GOAL_MODELS,
) -> list[WalkForwardMetric]:
    metrics: list[WalkForwardMetric] = []
    for model_factory, model_name in models:
        metrics.extend(
            run_goal_model_walk_forward(
                matches,
                start_season=start_season,
                end_season=end_season,
                initial_train_seasons=initial_train_seasons,
                seasons=seasons,
                model_factory=model_factory,
                model_name=model_name,
            )
        )
    return metrics


def _predict_rows(
    model: DixonColesMatchModel,
    matches: Sequence[MatchResult],
    model_name: str,
) -> list[PredictionRow]:
    pairs = [(match.home_team, match.away_team) for match in matches]
    probabilities = model.predict_many(pairs)
    return [
        PredictionRow(model=model_name, match=match, probabilities=probability)
        for match, probability in zip(matches, probabilities, strict=True)
        if probability is not None
    ]

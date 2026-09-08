"""Walk-forward para el Elo ajustado por altitud.

Elo es secuencial, no se reentrena por ventana: para cada temporada de
evaluacion se recorren las previas para dejar los ratings al dia y luego se
predice la temporada evaluada partido a partido.

Los partidos que comparten kickoff se predicen todos con el estado ANTERIOR a
aplicar cualquiera de ellos, igual que hace `run_baseline_backtest`. Si no, el
primer partido de una jornada le filtraria informacion al resto.
"""

from __future__ import annotations

from collections.abc import Sequence

from futpredict.data.football_data_uk_catalog import season_range
from futpredict.domain.matches import MatchResult
from futpredict.evaluation.backtest import PredictionRow, summarize_predictions
from futpredict.evaluation.walk_forward import (
    DEFAULT_INITIAL_TRAIN_SEASONS,
    WalkForwardMetric,
)
from futpredict.evaluation.walk_forward_predictions import WalkForwardPrediction
from futpredict.models.altitude_elo import (
    ALTITUDE_ELO_MODEL_NAME,
    AltitudeEloConfig,
    AltitudeEloModel,
)


def predict_sequence(
    model: AltitudeEloModel,
    matches: Sequence[MatchResult],
    model_name: str = ALTITUDE_ELO_MODEL_NAME,
) -> list[PredictionRow]:
    """Predice y actualiza en orden, por bloques de mismo kickoff."""
    ordered = sorted(matches, key=lambda match: match.kickoff_utc)
    rows: list[PredictionRow] = []
    index = 0
    while index < len(ordered):
        kickoff = ordered[index].kickoff_utc
        block: list[MatchResult] = []
        while index < len(ordered) and ordered[index].kickoff_utc == kickoff:
            block.append(ordered[index])
            index += 1
        for match in block:
            rows.append(PredictionRow(model_name, match, model.predict_proba(match)))
        for match in block:
            model.observe(match)
    return rows


def _window_rows(
    matches: Sequence[MatchResult],
    *,
    start_season: str,
    end_season: str,
    initial_train_seasons: int,
    seasons: Sequence[str] | None,
    config: AltitudeEloConfig | None,
    model_name: str,
) -> list[tuple[str, str, str, str, list[MatchResult], list[MatchResult], list[PredictionRow]]]:
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

    windows = []
    for division, division_matches in sorted(by_division.items()):
        ordered = sorted(division_matches, key=lambda match: match.kickoff_utc)
        for eval_index in range(initial_train_seasons, len(season_list)):
            train_seasons = set(season_list[:eval_index])
            eval_season = season_list[eval_index]
            train_matches = [match for match in ordered if match.season in train_seasons]
            eval_matches = [match for match in ordered if match.season == eval_season]
            if not train_matches or not eval_matches:
                continue
            model = AltitudeEloModel(config).fit(train_matches)
            rows = predict_sequence(model, eval_matches, model_name)
            if not rows:
                continue
            windows.append(
                (
                    division,
                    eval_season,
                    season_list[0],
                    season_list[eval_index - 1],
                    train_matches,
                    eval_matches,
                    rows,
                )
            )
    return windows


def run_altitude_elo_walk_forward(
    matches: Sequence[MatchResult],
    *,
    start_season: str,
    end_season: str,
    initial_train_seasons: int = DEFAULT_INITIAL_TRAIN_SEASONS,
    seasons: Sequence[str] | None = None,
    config: AltitudeEloConfig | None = None,
    model_name: str = ALTITUDE_ELO_MODEL_NAME,
) -> list[WalkForwardMetric]:
    metrics: list[WalkForwardMetric] = []
    for division, eval_season, first, previous, train, evaluated, rows in _window_rows(
        matches,
        start_season=start_season,
        end_season=end_season,
        initial_train_seasons=initial_train_seasons,
        seasons=seasons,
        config=config,
        model_name=model_name,
    ):
        for summary in summarize_predictions(rows):
            metrics.append(
                WalkForwardMetric(
                    division=division,
                    evaluation_season=eval_season,
                    train_start_season=first,
                    train_end_season=previous,
                    train_window_start_utc=train[0].kickoff_utc,
                    train_window_end_utc=train[-1].kickoff_utc,
                    eval_window_start_utc=evaluated[0].kickoff_utc,
                    eval_window_end_utc=evaluated[-1].kickoff_utc,
                    summary=summary,
                )
            )
    return metrics


def run_altitude_elo_walk_forward_predictions(
    matches: Sequence[MatchResult],
    *,
    start_season: str,
    end_season: str,
    initial_train_seasons: int = DEFAULT_INITIAL_TRAIN_SEASONS,
    seasons: Sequence[str] | None = None,
    config: AltitudeEloConfig | None = None,
    model_name: str = ALTITUDE_ELO_MODEL_NAME,
) -> list[WalkForwardPrediction]:
    predictions: list[WalkForwardPrediction] = []
    for division, eval_season, first, previous, train, evaluated, rows in _window_rows(
        matches,
        start_season=start_season,
        end_season=end_season,
        initial_train_seasons=initial_train_seasons,
        seasons=seasons,
        config=config,
        model_name=model_name,
    ):
        for row in rows:
            predictions.append(
                WalkForwardPrediction(
                    division=division,
                    evaluation_season=eval_season,
                    train_start_season=first,
                    train_end_season=previous,
                    train_window_start_utc=train[0].kickoff_utc,
                    train_window_end_utc=train[-1].kickoff_utc,
                    eval_window_start_utc=evaluated[0].kickoff_utc,
                    eval_window_end_utc=evaluated[-1].kickoff_utc,
                    prediction=row,
                )
            )
    return predictions

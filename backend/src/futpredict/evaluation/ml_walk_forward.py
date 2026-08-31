"""Walk-forward temporal para modelos ML entrenados (features + etiqueta).

Paralelo a `run_expanding_walk_forward` (baselines), pero cada ventana entrena
el modelo sobre las temporadas previas y predice la temporada de evaluacion.
Mantiene el anti-leakage: solo entrena con partidos de temporadas anteriores y
usa features cuyo corte es anterior al kickoff del partido.

Es agnostico del modelo: recibe una fabrica que construye un modelo nuevo por
ventana. Asi la logistica y el boosting reutilizan el mismo recorrido.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Protocol

from futpredict.data.football_data_uk_catalog import season_range
from futpredict.domain.matches import MatchResult
from futpredict.evaluation.backtest import PredictionRow, summarize_predictions
from futpredict.evaluation.walk_forward import (
    DEFAULT_INITIAL_TRAIN_SEASONS,
    WalkForwardMetric,
)
from futpredict.models.gradient_boosting import (
    GRADIENT_BOOSTING_MODEL_NAME,
    GradientBoostingMatchModel,
)
from futpredict.models.logistic import (
    LOGISTIC_MODEL_NAME,
    FeatureValues,
    LogisticMatchModel,
    MatchFeatureSample,
)

MIN_TRAIN_SAMPLES = 50


class SupportsMatchProbabilities(Protocol):
    def fit(self, samples: Sequence[MatchFeatureSample]) -> SupportsMatchProbabilities: ...

    def predict_proba(self, features: FeatureValues) -> tuple[float, float, float]: ...


ModelFactory = Callable[[], SupportsMatchProbabilities]

# Modelos ML entrenados que se evaluan/persisten junto a los baselines.
DEFAULT_ML_MODELS: tuple[tuple[ModelFactory, str], ...] = (
    (LogisticMatchModel, LOGISTIC_MODEL_NAME),
    (GradientBoostingMatchModel, GRADIENT_BOOSTING_MODEL_NAME),
)


def run_configured_ml_walk_forward(
    matches: Sequence[MatchResult],
    feature_payloads: Mapping[int, FeatureValues],
    *,
    start_season: str,
    end_season: str,
    initial_train_seasons: int = DEFAULT_INITIAL_TRAIN_SEASONS,
    min_train_samples: int = MIN_TRAIN_SAMPLES,
    models: Sequence[tuple[ModelFactory, str]] = DEFAULT_ML_MODELS,
) -> list[WalkForwardMetric]:
    metrics: list[WalkForwardMetric] = []
    for model_factory, model_name in models:
        metrics.extend(
            run_ml_walk_forward(
                matches,
                feature_payloads,
                start_season=start_season,
                end_season=end_season,
                initial_train_seasons=initial_train_seasons,
                min_train_samples=min_train_samples,
                model_factory=model_factory,
                model_name=model_name,
            )
        )
    return metrics


def run_ml_walk_forward(
    matches: Sequence[MatchResult],
    feature_payloads: Mapping[int, FeatureValues],
    *,
    start_season: str,
    end_season: str,
    initial_train_seasons: int = DEFAULT_INITIAL_TRAIN_SEASONS,
    min_train_samples: int = MIN_TRAIN_SAMPLES,
    model_factory: ModelFactory = LogisticMatchModel,
    model_name: str = LOGISTIC_MODEL_NAME,
) -> list[WalkForwardMetric]:
    seasons = season_range(start_season, end_season)
    if initial_train_seasons < 1:
        msg = "initial_train_seasons must be positive"
        raise ValueError(msg)
    if len(seasons) <= initial_train_seasons:
        msg = "season range must leave at least one evaluation season"
        raise ValueError(msg)

    season_set = set(seasons)
    materialized = [match for match in matches if match.season in season_set]
    by_division: dict[str, list[MatchResult]] = {}
    for match in materialized:
        by_division.setdefault(match.division, []).append(match)

    metrics: list[WalkForwardMetric] = []
    for division, division_matches in sorted(by_division.items()):
        ordered = sorted(division_matches, key=lambda match: match.kickoff_utc)
        for eval_index in range(initial_train_seasons, len(seasons)):
            train_seasons = set(seasons[:eval_index])
            eval_season = seasons[eval_index]
            train_matches = [match for match in ordered if match.season in train_seasons]
            eval_matches = [match for match in ordered if match.season == eval_season]
            if not train_matches or not eval_matches:
                continue

            samples = _training_samples(train_matches, feature_payloads)
            if len(samples) < min_train_samples:
                continue
            if len({sample.outcome for sample in samples}) < 2:
                continue

            model = model_factory().fit(samples)
            eval_rows = _predict_rows(model, eval_matches, feature_payloads, model_name)
            if not eval_rows:
                continue

            for summary in summarize_predictions(eval_rows):
                metrics.append(
                    WalkForwardMetric(
                        division=division,
                        evaluation_season=eval_season,
                        train_start_season=seasons[0],
                        train_end_season=seasons[eval_index - 1],
                        train_window_start_utc=train_matches[0].kickoff_utc,
                        train_window_end_utc=train_matches[-1].kickoff_utc,
                        eval_window_start_utc=eval_matches[0].kickoff_utc,
                        eval_window_end_utc=eval_matches[-1].kickoff_utc,
                        summary=summary,
                    )
                )
    return metrics


def _training_samples(
    matches: Sequence[MatchResult],
    feature_payloads: Mapping[int, FeatureValues],
) -> list[MatchFeatureSample]:
    samples: list[MatchFeatureSample] = []
    for match in matches:
        if match.match_id is None:
            continue
        payload = feature_payloads.get(match.match_id)
        if payload is None:
            continue
        samples.append(MatchFeatureSample(features=payload, outcome=match.outcome))
    return samples


def _predict_rows(
    model: SupportsMatchProbabilities,
    matches: Sequence[MatchResult],
    feature_payloads: Mapping[int, FeatureValues],
    model_name: str,
) -> list[PredictionRow]:
    rows: list[PredictionRow] = []
    for match in matches:
        if match.match_id is None:
            continue
        payload = feature_payloads.get(match.match_id)
        if payload is None:
            continue
        rows.append(
            PredictionRow(
                model=model_name,
                match=match,
                probabilities=model.predict_proba(payload),
            )
        )
    return rows

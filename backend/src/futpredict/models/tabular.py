"""Maquinaria compartida de los modelos tabulares 1X2.

Define el contrato de features/etiqueta y una clase base que envuelve cualquier
clasificador scikit-learn (probabilistico) para producir tuplas (H, D, A). La
usan la logistica, el gradient boosting y las variantes calibradas.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np
from numpy.typing import NDArray

# Orden fijo de features del set rolling_v1. Define las columnas de la matriz X.
FEATURE_KEYS: tuple[str, ...] = (
    "home_team_matches_before",
    "away_team_matches_before",
    "home_points_per_match_last_5",
    "away_points_per_match_last_5",
    "home_goals_for_per_match_last_5",
    "away_goals_for_per_match_last_5",
    "home_goals_against_per_match_last_5",
    "away_goals_against_per_match_last_5",
    "home_days_since_last_match",
    "away_days_since_last_match",
    "league_home_win_rate_before",
    "league_draw_rate_before",
    "league_away_win_rate_before",
)

# Features de xG (feature set rolling_v2 = rolling_v1 + estas 4).
XG_FEATURE_KEYS: tuple[str, ...] = (
    "home_xg_for_per_match_last_5",
    "away_xg_for_per_match_last_5",
    "home_xg_against_per_match_last_5",
    "away_xg_against_per_match_last_5",
)
FEATURE_KEYS_V2: tuple[str, ...] = (*FEATURE_KEYS, *XG_FEATURE_KEYS)

OUTCOMES: tuple[str, str, str] = ("H", "D", "A")
OUTCOME_INDEX: dict[str, int] = {"H": 0, "D": 1, "A": 2}

type FeatureValues = Mapping[str, float | int | None]


@dataclass(frozen=True)
class MatchFeatureSample:
    features: FeatureValues
    outcome: str


class TabularMatchModel:
    """Base: envuelve un estimador sklearn probabilistico para 1X2."""

    _model_label: str = "tabular model"

    def __init__(self, estimator: Any, *, feature_keys: Sequence[str] = FEATURE_KEYS) -> None:
        self._estimator = estimator
        self.feature_keys: tuple[str, ...] = tuple(feature_keys)
        self._fitted = False

    def fit(self, samples: Sequence[MatchFeatureSample]) -> TabularMatchModel:
        validate_training_samples(samples, model_label=self._model_label)
        matrix = feature_matrix([sample.features for sample in samples], self.feature_keys)
        self._estimator.fit(matrix, target_vector(samples))
        self._fitted = True
        return self

    def predict_proba(self, features: FeatureValues) -> tuple[float, float, float]:
        if not self._fitted:
            msg = f"{self._model_label} must be fitted before predicting"
            raise ValueError(msg)
        raw = self._estimator.predict_proba(feature_matrix([features], self.feature_keys))[0]
        return probabilities_from_classes(raw, self._estimator.classes_)


def validate_training_samples(
    samples: Sequence[MatchFeatureSample],
    *,
    model_label: str,
) -> None:
    if len(samples) < 3:
        msg = f"{model_label} needs at least 3 training samples"
        raise ValueError(msg)
    outcomes = {sample.outcome for sample in samples}
    if not outcomes.issubset(set(OUTCOMES)):
        msg = f"unexpected outcomes in training samples: {sorted(outcomes - set(OUTCOMES))}"
        raise ValueError(msg)
    if len(outcomes) < 2:
        msg = f"{model_label} needs at least two distinct outcomes to train"
        raise ValueError(msg)


def feature_matrix(
    rows: Sequence[FeatureValues],
    feature_keys: Sequence[str],
) -> NDArray[np.float64]:
    data = [[_as_float(features.get(key)) for key in feature_keys] for features in rows]
    return np.array(data, dtype=float)


def target_vector(samples: Sequence[MatchFeatureSample]) -> NDArray[np.int_]:
    return np.array([OUTCOME_INDEX[sample.outcome] for sample in samples])


def probabilities_from_classes(raw: Any, classes: Any) -> tuple[float, float, float]:
    probabilities = [0.0, 0.0, 0.0]
    for column, class_label in enumerate(classes):
        probabilities[int(class_label)] = float(raw[column])
    return _normalize(probabilities)


def _as_float(value: float | int | None) -> float:
    if value is None:
        return math.nan
    return float(value)


def _normalize(probabilities: list[float]) -> tuple[float, float, float]:
    total = sum(probabilities)
    if total <= 0:
        return (1 / 3, 1 / 3, 1 / 3)
    return (
        probabilities[0] / total,
        probabilities[1] / total,
        probabilities[2] / total,
    )

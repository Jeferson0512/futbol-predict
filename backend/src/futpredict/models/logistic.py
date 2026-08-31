"""Regresion logistica multinomial para 1X2 sobre features tabulares.

Es el primer modelo entrenado real del proyecto (mas alla de los baselines).
Consume el feature set `rolling_v1` y produce probabilidades (H, D, A) que se
evaluan con el mismo RPS/log-loss/Brier que los baselines.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

LOGISTIC_MODEL_NAME = "logistic_regression"
LOGISTIC_ALGORITHM = "multinomial_logit"

# Orden fijo de features del set rolling_v1. El orden importa: define las
# columnas de la matriz X y debe ser estable entre entrenamiento y prediccion.
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

_OUTCOMES: tuple[str, str, str] = ("H", "D", "A")
_OUTCOME_INDEX: dict[str, int] = {"H": 0, "D": 1, "A": 2}

type FeatureValues = Mapping[str, float | int | None]


@dataclass(frozen=True)
class MatchFeatureSample:
    features: FeatureValues
    outcome: str


class LogisticMatchModel:
    """Envuelve un pipeline imputacion -> escalado -> logistica multinomial."""

    def __init__(
        self,
        *,
        feature_keys: Sequence[str] = FEATURE_KEYS,
        c: float = 1.0,
        max_iter: int = 1000,
    ) -> None:
        self.feature_keys: tuple[str, ...] = tuple(feature_keys)
        self._pipeline = Pipeline(
            steps=[
                ("impute", SimpleImputer(strategy="mean")),
                ("scale", StandardScaler()),
                ("clf", LogisticRegression(C=c, max_iter=max_iter)),
            ]
        )
        self._fitted = False

    def fit(self, samples: Sequence[MatchFeatureSample]) -> LogisticMatchModel:
        if len(samples) < 3:
            msg = "logistic model needs at least 3 training samples"
            raise ValueError(msg)
        outcomes = {sample.outcome for sample in samples}
        if not outcomes.issubset(set(_OUTCOMES)):
            msg = f"unexpected outcomes in training samples: {sorted(outcomes - set(_OUTCOMES))}"
            raise ValueError(msg)
        if len(outcomes) < 2:
            msg = "logistic model needs at least two distinct outcomes to train"
            raise ValueError(msg)

        matrix = self._matrix([sample.features for sample in samples])
        targets = np.array([_OUTCOME_INDEX[sample.outcome] for sample in samples])
        self._pipeline.fit(matrix, targets)
        self._fitted = True
        return self

    def predict_proba(self, features: FeatureValues) -> tuple[float, float, float]:
        if not self._fitted:
            msg = "logistic model must be fitted before predicting"
            raise ValueError(msg)
        row = self._matrix([features])
        raw = self._pipeline.predict_proba(row)[0]
        classes = self._pipeline.classes_
        probabilities = [0.0, 0.0, 0.0]
        for column, class_label in enumerate(classes):
            probabilities[int(class_label)] = float(raw[column])
        return _normalize(probabilities)

    def _matrix(self, rows: Sequence[FeatureValues]) -> NDArray[np.float64]:
        data = [
            [_as_float(features.get(key)) for key in self.feature_keys] for features in rows
        ]
        return np.array(data, dtype=float)


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

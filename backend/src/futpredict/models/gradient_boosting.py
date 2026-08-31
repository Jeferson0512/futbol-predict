"""Gradient boosting (histogramas) para 1X2 sobre features tabulares.

Usa `HistGradientBoostingClassifier` de scikit-learn: boosting por histogramas
al estilo LightGBM, ya incluido en el extra `ml`, que maneja NaN nativamente
(no necesita imputacion ni escalado). Comparte el contrato de features/etiqueta
con la regresion logistica para reutilizar el walk-forward ML.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

import numpy as np
from numpy.typing import NDArray
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.pipeline import Pipeline

from futpredict.models.logistic import FEATURE_KEYS, FeatureValues, MatchFeatureSample

GRADIENT_BOOSTING_MODEL_NAME = "gradient_boosting"
GRADIENT_BOOSTING_ALGORITHM = "gradient_boosting"

_OUTCOMES: tuple[str, str, str] = ("H", "D", "A")
_OUTCOME_INDEX: dict[str, int] = {"H": 0, "D": 1, "A": 2}


class GradientBoostingMatchModel:
    """Envuelve un HistGradientBoostingClassifier multiclase para 1X2."""

    def __init__(
        self,
        *,
        feature_keys: Sequence[str] = FEATURE_KEYS,
        max_iter: int = 400,
        learning_rate: float = 0.03,
        max_leaf_nodes: int = 15,
        min_samples_leaf: int = 80,
        l2_regularization: float = 5.0,
        early_stopping: bool = True,
        validation_fraction: float = 0.15,
        n_iter_no_change: int = 20,
        random_state: int = 0,
    ) -> None:
        # Regularizacion fuerte + early stopping: con solo 13 features y cambio
        # de distribucion entre temporadas, un boosting profundo sobreajusta.
        self.feature_keys: tuple[str, ...] = tuple(feature_keys)
        self._pipeline = Pipeline(
            steps=[
                (
                    "clf",
                    HistGradientBoostingClassifier(
                        max_iter=max_iter,
                        learning_rate=learning_rate,
                        max_leaf_nodes=max_leaf_nodes,
                        min_samples_leaf=min_samples_leaf,
                        l2_regularization=l2_regularization,
                        early_stopping=early_stopping,
                        validation_fraction=validation_fraction,
                        n_iter_no_change=n_iter_no_change,
                        random_state=random_state,
                    ),
                ),
            ]
        )
        self._fitted = False

    def fit(self, samples: Sequence[MatchFeatureSample]) -> GradientBoostingMatchModel:
        if len(samples) < 3:
            msg = "gradient boosting model needs at least 3 training samples"
            raise ValueError(msg)
        outcomes = {sample.outcome for sample in samples}
        if not outcomes.issubset(set(_OUTCOMES)):
            msg = f"unexpected outcomes in training samples: {sorted(outcomes - set(_OUTCOMES))}"
            raise ValueError(msg)
        if len(outcomes) < 2:
            msg = "gradient boosting model needs at least two distinct outcomes to train"
            raise ValueError(msg)

        matrix = self._matrix([sample.features for sample in samples])
        targets = np.array([_OUTCOME_INDEX[sample.outcome] for sample in samples])
        self._pipeline.fit(matrix, targets)
        self._fitted = True
        return self

    def predict_proba(self, features: FeatureValues) -> tuple[float, float, float]:
        if not self._fitted:
            msg = "gradient boosting model must be fitted before predicting"
            raise ValueError(msg)
        raw = self._pipeline.predict_proba(self._matrix([features]))[0]
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

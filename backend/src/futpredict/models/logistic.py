"""Regresion logistica multinomial para 1X2 sobre features tabulares.

Primer modelo entrenado real del proyecto (mas alla de los baselines). Consume
el feature set `rolling_v1` y produce probabilidades (H, D, A) evaluadas con el
mismo RPS/log-loss/Brier que los baselines.
"""

from __future__ import annotations

from collections.abc import Sequence

from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from futpredict.models.tabular import FEATURE_KEYS, TabularMatchModel

LOGISTIC_MODEL_NAME = "logistic_regression"
LOGISTIC_ALGORITHM = "multinomial_logit"


def build_logistic_estimator(*, c: float = 1.0, max_iter: int = 1000) -> Pipeline:
    return Pipeline(
        steps=[
            ("impute", SimpleImputer(strategy="mean")),
            ("scale", StandardScaler()),
            ("clf", LogisticRegression(C=c, max_iter=max_iter)),
        ]
    )


class LogisticMatchModel(TabularMatchModel):
    """Pipeline imputacion -> escalado -> logistica multinomial."""

    _model_label = "logistic model"

    def __init__(
        self,
        *,
        feature_keys: Sequence[str] = FEATURE_KEYS,
        c: float = 1.0,
        max_iter: int = 1000,
    ) -> None:
        super().__init__(
            build_logistic_estimator(c=c, max_iter=max_iter),
            feature_keys=feature_keys,
        )

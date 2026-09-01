"""Gradient boosting (histogramas) para 1X2 sobre features tabulares.

Usa `HistGradientBoostingClassifier` de scikit-learn: boosting por histogramas
al estilo LightGBM, ya incluido en el extra `ml`, que maneja NaN nativamente
(no necesita imputacion ni escalado). Regularizado con early stopping porque con
solo 13 features y cambio de distribucion entre temporadas sobreajusta facil.
"""

from __future__ import annotations

from collections.abc import Sequence

from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.pipeline import Pipeline

from futpredict.models.tabular import FEATURE_KEYS, TabularMatchModel

GRADIENT_BOOSTING_MODEL_NAME = "gradient_boosting"
GRADIENT_BOOSTING_ALGORITHM = "gradient_boosting"


def build_gradient_boosting_estimator(
    *,
    max_iter: int = 400,
    learning_rate: float = 0.03,
    max_leaf_nodes: int = 15,
    min_samples_leaf: int = 80,
    l2_regularization: float = 5.0,
    early_stopping: bool = True,
    validation_fraction: float = 0.15,
    n_iter_no_change: int = 20,
    random_state: int = 0,
) -> Pipeline:
    return Pipeline(
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


class GradientBoostingMatchModel(TabularMatchModel):
    """HistGradientBoostingClassifier multiclase para 1X2."""

    _model_label = "gradient boosting model"

    def __init__(
        self,
        *,
        feature_keys: Sequence[str] = FEATURE_KEYS,
        max_iter: int = 400,
    ) -> None:
        super().__init__(
            build_gradient_boosting_estimator(max_iter=max_iter),
            feature_keys=feature_keys,
        )

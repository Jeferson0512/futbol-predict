"""Calibracion de probabilidades (Platt/isotonica) para modelos 1X2.

Envuelve un estimador base en `CalibratedClassifierCV`, que ajusta la
calibracion por validacion cruzada dentro de la ventana de entrenamiento (sin
usar la temporada de evaluacion). Mejora log-loss/Brier al alinear las
probabilidades predichas con las frecuencias observadas.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Literal

from sklearn.calibration import CalibratedClassifierCV

from futpredict.models.logistic import build_logistic_estimator
from futpredict.models.tabular import FEATURE_KEYS, TabularMatchModel

CALIBRATED_LOGISTIC_MODEL_NAME = "logistic_calibrated"
CALIBRATED_LOGISTIC_ALGORITHM = "logistic_isotonic"

type CalibrationMethod = Literal["isotonic", "sigmoid"]


class CalibratedMatchModel(TabularMatchModel):
    """Estimador base calibrado (isotonica o Platt) por validacion cruzada."""

    def __init__(
        self,
        base_estimator: Any,
        *,
        method: CalibrationMethod = "isotonic",
        cv: int = 3,
        feature_keys: Sequence[str] = FEATURE_KEYS,
        model_label: str = "calibrated model",
    ) -> None:
        self._model_label = model_label
        super().__init__(
            CalibratedClassifierCV(estimator=base_estimator, method=method, cv=cv),
            feature_keys=feature_keys,
        )


def build_calibrated_logistic_model() -> CalibratedMatchModel:
    return CalibratedMatchModel(
        build_logistic_estimator(),
        method="isotonic",
        model_label="calibrated logistic model",
    )

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import cast

from sqlalchemy import Table, delete, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from futpredict.db.models import CalibrationBin, ModelMetric, ModelVersion, Prediction
from futpredict.evaluation.calibration import (
    CalibrationBinSummary,
    CalibrationSample,
    build_calibration_bins,
    expected_calibration_error,
)

SUPPORTED_OUTCOMES = ("H", "D", "A")


@dataclass(frozen=True)
class CalibrationBuild:
    bins: list[CalibrationBinSummary]
    class_samples: int


@dataclass(frozen=True)
class CalibrationPersistenceSummary:
    model_versions: int
    bins: int
    class_samples: int
    n_bins: int


def build_calibration_from_predictions(
    session: Session,
    *,
    n_bins: int = 10,
    model_names: Sequence[str] | None = None,
) -> CalibrationBuild:
    samples = load_calibration_samples_from_db(session, model_names=model_names)
    return CalibrationBuild(
        bins=build_calibration_bins(samples, n_bins=n_bins),
        class_samples=len(samples),
    )


def load_calibration_samples_from_db(
    session: Session,
    *,
    model_names: Sequence[str] | None = None,
) -> list[CalibrationSample]:
    statement = (
        select(
            Prediction.model_version_id,
            Prediction.prob_home,
            Prediction.prob_draw,
            Prediction.prob_away,
            Prediction.actual_outcome,
        )
        .where(Prediction.actual_outcome.in_(SUPPORTED_OUTCOMES))
        .order_by(Prediction.model_version_id, Prediction.id)
    )
    if model_names:
        statement = statement.join(
            ModelVersion,
            ModelVersion.id == Prediction.model_version_id,
        ).where(ModelVersion.name.in_(model_names))

    samples: list[CalibrationSample] = []
    for row in session.execute(statement):
        model_version_id = cast(int, row[0])
        actual_outcome = cast(str, row[4])
        samples.extend(
            [
                CalibrationSample(
                    model_version_id=model_version_id,
                    outcome="H",
                    predicted_probability=float(row[1]),
                    observed=actual_outcome == "H",
                ),
                CalibrationSample(
                    model_version_id=model_version_id,
                    outcome="D",
                    predicted_probability=float(row[2]),
                    observed=actual_outcome == "D",
                ),
                CalibrationSample(
                    model_version_id=model_version_id,
                    outcome="A",
                    predicted_probability=float(row[3]),
                    observed=actual_outcome == "A",
                ),
            ]
        )
    return samples


def upsert_calibration_bins(
    session: Session,
    calibration: CalibrationBuild,
    *,
    evaluated_at: datetime | None = None,
    commit: bool = True,
) -> CalibrationPersistenceSummary:
    timestamp = evaluated_at if evaluated_at is not None else datetime.now(UTC)
    model_version_ids = sorted({bin_summary.model_version_id for bin_summary in calibration.bins})
    n_bins_values = {bin_summary.n_bins for bin_summary in calibration.bins}
    n_bins = n_bins_values.pop() if n_bins_values else 10
    if n_bins_values:
        msg = "calibration build must contain a single n_bins value"
        raise ValueError(msg)

    if model_version_ids:
        session.execute(
            delete(CalibrationBin).where(
                CalibrationBin.model_version_id.in_(model_version_ids),
                CalibrationBin.n_bins == n_bins,
            )
        )
        _insert_calibration_bin_rows(session, calibration.bins, timestamp)
        _update_model_metric_calibration_errors(session, calibration.bins)

    if commit:
        session.commit()

    return CalibrationPersistenceSummary(
        model_versions=len(model_version_ids),
        bins=len(calibration.bins),
        class_samples=calibration.class_samples,
        n_bins=n_bins,
    )


def calibration_status_rows(session: Session, *, n_bins: int = 10) -> list[dict[str, object]]:
    weighted_error = (
        func.sum(CalibrationBin.calibration_error * CalibrationBin.n_predictions)
        / func.sum(CalibrationBin.n_predictions)
    )
    rows = session.execute(
        select(
            ModelVersion.name.label("model"),
            ModelVersion.algorithm,
            ModelVersion.feature_set_version,
            func.count(func.distinct(CalibrationBin.model_version_id)).label("model_versions"),
            func.count(CalibrationBin.id).label("bins"),
            func.sum(CalibrationBin.n_predictions).label("class_samples"),
            weighted_error.label("calibration_error"),
        )
        .join(ModelVersion, ModelVersion.id == CalibrationBin.model_version_id)
        .where(CalibrationBin.n_bins == n_bins)
        .group_by(
            ModelVersion.name,
            ModelVersion.algorithm,
            ModelVersion.feature_set_version,
        )
        .order_by(weighted_error)
    ).mappings()
    return [dict(row) for row in rows]


def calibration_curve_rows(
    session: Session,
    *,
    n_bins: int = 10,
    model_name: str | None = None,
) -> list[dict[str, object]]:
    total_predictions = func.sum(CalibrationBin.n_predictions)
    avg_probability = (
        func.sum(CalibrationBin.avg_predicted_probability * CalibrationBin.n_predictions)
        / total_predictions
    )
    observed_frequency = (
        func.sum(CalibrationBin.observed_frequency * CalibrationBin.n_predictions)
        / total_predictions
    )
    calibration_error = func.abs(avg_probability - observed_frequency)
    statement = (
        select(
            ModelVersion.name.label("model"),
            ModelVersion.algorithm,
            ModelVersion.feature_set_version,
            CalibrationBin.outcome,
            CalibrationBin.n_bins,
            CalibrationBin.bin_index,
            CalibrationBin.bin_lower,
            CalibrationBin.bin_upper,
            total_predictions.label("n_predictions"),
            avg_probability.label("avg_predicted_probability"),
            observed_frequency.label("observed_frequency"),
            calibration_error.label("calibration_error"),
        )
        .join(ModelVersion, ModelVersion.id == CalibrationBin.model_version_id)
        .where(CalibrationBin.n_bins == n_bins)
        .group_by(
            ModelVersion.name,
            ModelVersion.algorithm,
            ModelVersion.feature_set_version,
            CalibrationBin.outcome,
            CalibrationBin.n_bins,
            CalibrationBin.bin_index,
            CalibrationBin.bin_lower,
            CalibrationBin.bin_upper,
        )
        .order_by(
            ModelVersion.name,
            CalibrationBin.outcome,
            CalibrationBin.bin_index,
        )
    )
    if model_name is not None:
        statement = statement.where(ModelVersion.name == model_name)

    return [dict(row) for row in session.execute(statement).mappings()]


def _insert_calibration_bin_rows(
    session: Session,
    bins: Sequence[CalibrationBinSummary],
    timestamp: datetime,
) -> None:
    if not bins:
        return

    table = cast(Table, CalibrationBin.__table__)
    rows = [
        {
            "model_version_id": bin_summary.model_version_id,
            "evaluated_at": timestamp,
            "outcome": bin_summary.outcome,
            "n_bins": bin_summary.n_bins,
            "bin_index": bin_summary.bin_index,
            "bin_lower": _metric_decimal(bin_summary.bin_lower),
            "bin_upper": _metric_decimal(bin_summary.bin_upper),
            "n_predictions": bin_summary.n_predictions,
            "avg_predicted_probability": _metric_decimal(
                bin_summary.avg_predicted_probability
            ),
            "observed_frequency": _metric_decimal(bin_summary.observed_frequency),
            "calibration_error": _metric_decimal(bin_summary.calibration_error),
        }
        for bin_summary in bins
    ]
    base = insert(table).values(rows)
    statement = base.on_conflict_do_update(
        constraint="uq_calibration_bin_identity",
        set_={
            "evaluated_at": base.excluded.evaluated_at,
            "n_predictions": base.excluded.n_predictions,
            "avg_predicted_probability": base.excluded.avg_predicted_probability,
            "observed_frequency": base.excluded.observed_frequency,
            "calibration_error": base.excluded.calibration_error,
        },
    )
    session.execute(statement)


def _update_model_metric_calibration_errors(
    session: Session,
    bins: Sequence[CalibrationBinSummary],
) -> None:
    bins_by_model_version: dict[int, list[CalibrationBinSummary]] = {}
    for bin_summary in bins:
        bins_by_model_version.setdefault(bin_summary.model_version_id, []).append(bin_summary)

    for model_version_id, model_bins in bins_by_model_version.items():
        session.execute(
            update(ModelMetric)
            .where(ModelMetric.model_version_id == model_version_id)
            .values(calibration_error=_metric_decimal(expected_calibration_error(model_bins)))
        )


def _metric_decimal(value: float) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.00000001"))

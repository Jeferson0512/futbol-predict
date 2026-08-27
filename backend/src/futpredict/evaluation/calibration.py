from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass


@dataclass(frozen=True)
class CalibrationSample:
    model_version_id: int
    outcome: str
    predicted_probability: float
    observed: bool


@dataclass(frozen=True)
class CalibrationBinSummary:
    model_version_id: int
    outcome: str
    n_bins: int
    bin_index: int
    bin_lower: float
    bin_upper: float
    n_predictions: int
    avg_predicted_probability: float
    observed_frequency: float
    calibration_error: float


def build_calibration_bins(
    samples: Iterable[CalibrationSample],
    *,
    n_bins: int = 10,
) -> list[CalibrationBinSummary]:
    if n_bins < 1:
        msg = "n_bins must be positive"
        raise ValueError(msg)

    grouped: dict[tuple[int, str, int], list[CalibrationSample]] = {}
    for sample in samples:
        if sample.predicted_probability < 0 or sample.predicted_probability > 1:
            msg = (
                "predicted probability must be between 0 and 1, "
                f"got {sample.predicted_probability}"
            )
            raise ValueError(msg)
        bin_index = min(int(sample.predicted_probability * n_bins), n_bins - 1)
        grouped.setdefault((sample.model_version_id, sample.outcome, bin_index), []).append(sample)

    summaries: list[CalibrationBinSummary] = []
    for (model_version_id, outcome, bin_index), bin_samples in sorted(grouped.items()):
        avg_probability = sum(sample.predicted_probability for sample in bin_samples) / len(
            bin_samples
        )
        observed_frequency = sum(1 for sample in bin_samples if sample.observed) / len(
            bin_samples
        )
        summaries.append(
            CalibrationBinSummary(
                model_version_id=model_version_id,
                outcome=outcome,
                n_bins=n_bins,
                bin_index=bin_index,
                bin_lower=bin_index / n_bins,
                bin_upper=(bin_index + 1) / n_bins,
                n_predictions=len(bin_samples),
                avg_predicted_probability=avg_probability,
                observed_frequency=observed_frequency,
                calibration_error=abs(avg_probability - observed_frequency),
            )
        )
    return summaries


def expected_calibration_error(bins: Iterable[CalibrationBinSummary]) -> float:
    materialized = list(bins)
    total_predictions = sum(bin_summary.n_predictions for bin_summary in materialized)
    if total_predictions == 0:
        return 0.0
    weighted_error = sum(
        bin_summary.calibration_error * bin_summary.n_predictions
        for bin_summary in materialized
    )
    return weighted_error / total_predictions

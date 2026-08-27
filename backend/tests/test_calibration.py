from __future__ import annotations

import pytest

from futpredict.evaluation.calibration import (
    CalibrationSample,
    build_calibration_bins,
    expected_calibration_error,
)


def test_build_calibration_bins_groups_samples_by_probability_bucket() -> None:
    bins = build_calibration_bins(
        [
            CalibrationSample(1, "H", 0.05, True),
            CalibrationSample(1, "H", 0.15, False),
            CalibrationSample(1, "H", 1.0, True),
        ],
        n_bins=10,
    )

    assert [(row.bin_index, row.n_predictions) for row in bins] == [(0, 1), (1, 1), (9, 1)]
    assert bins[0].avg_predicted_probability == 0.05
    assert bins[0].observed_frequency == 1.0
    assert bins[0].calibration_error == 0.95
    assert bins[-1].bin_lower == 0.9
    assert bins[-1].bin_upper == 1.0


def test_expected_calibration_error_is_weighted_by_predictions() -> None:
    bins = build_calibration_bins(
        [
            CalibrationSample(1, "D", 0.2, False),
            CalibrationSample(1, "D", 0.2, True),
            CalibrationSample(1, "D", 0.9, True),
        ],
        n_bins=2,
    )

    assert expected_calibration_error(bins) == pytest.approx(0.2333333333)


def test_build_calibration_bins_rejects_invalid_probability() -> None:
    with pytest.raises(ValueError, match="between 0 and 1"):
        build_calibration_bins([CalibrationSample(1, "A", 1.1, False)])

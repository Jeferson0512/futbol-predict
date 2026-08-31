from __future__ import annotations

import pytest

from futpredict.models.calibrated import build_calibrated_logistic_model
from futpredict.models.tabular import FEATURE_KEYS, MatchFeatureSample


def _features(home_points: float, away_points: float) -> dict[str, float | int | None]:
    values: dict[str, float | int | None] = dict.fromkeys(FEATURE_KEYS, 0.0)
    values["home_points_per_match_last_5"] = home_points
    values["away_points_per_match_last_5"] = away_points
    return values


def _training_set() -> list[MatchFeatureSample]:
    samples: list[MatchFeatureSample] = []
    for _ in range(30):
        samples.append(MatchFeatureSample(features=_features(3.0, 0.5), outcome="H"))
        samples.append(MatchFeatureSample(features=_features(0.5, 3.0), outcome="A"))
        samples.append(MatchFeatureSample(features=_features(1.6, 1.6), outcome="D"))
    return samples


def test_calibrated_logistic_predicts_valid_probabilities() -> None:
    model = build_calibrated_logistic_model().fit(_training_set())
    probs = model.predict_proba(_features(3.0, 0.5))
    assert abs(sum(probs) - 1.0) < 1e-9
    assert all(0.0 <= value <= 1.0 for value in probs)


def test_calibrated_logistic_predict_before_fit_raises() -> None:
    with pytest.raises(ValueError, match="must be fitted"):
        build_calibrated_logistic_model().predict_proba(_features(1.0, 1.0))

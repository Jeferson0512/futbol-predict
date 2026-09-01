from __future__ import annotations

import pytest

from futpredict.models.gradient_boosting import GradientBoostingMatchModel
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


def test_predict_proba_sums_to_one_and_learns_signal() -> None:
    model = GradientBoostingMatchModel(max_iter=80).fit(_training_set())

    prob_home, prob_draw, prob_away = model.predict_proba(_features(3.0, 0.5))
    assert abs((prob_home + prob_draw + prob_away) - 1.0) < 1e-9
    assert prob_home == max(prob_home, prob_draw, prob_away)


def test_predict_handles_missing_features() -> None:
    model = GradientBoostingMatchModel(max_iter=80).fit(_training_set())
    probs = model.predict_proba({"home_points_per_match_last_5": None})
    assert abs(sum(probs) - 1.0) < 1e-9


def test_predict_before_fit_raises() -> None:
    with pytest.raises(ValueError, match="must be fitted"):
        GradientBoostingMatchModel().predict_proba(_features(1.0, 1.0))

from __future__ import annotations

import pytest

from futpredict.models.logistic import LogisticMatchModel
from futpredict.models.tabular import FEATURE_KEYS, MatchFeatureSample


def _features(home_points: float, away_points: float) -> dict[str, float | int | None]:
    values: dict[str, float | int | None] = dict.fromkeys(FEATURE_KEYS, 0.0)
    values["home_points_per_match_last_5"] = home_points
    values["away_points_per_match_last_5"] = away_points
    return values


def _training_set() -> list[MatchFeatureSample]:
    samples: list[MatchFeatureSample] = []
    for _ in range(20):
        samples.append(MatchFeatureSample(features=_features(3.0, 0.5), outcome="H"))
        samples.append(MatchFeatureSample(features=_features(0.5, 3.0), outcome="A"))
        samples.append(MatchFeatureSample(features=_features(1.6, 1.6), outcome="D"))
    return samples


def test_predict_proba_sums_to_one_and_learns_signal() -> None:
    model = LogisticMatchModel(max_iter=2000).fit(_training_set())

    prob_home, prob_draw, prob_away = model.predict_proba(_features(3.0, 0.5))
    assert abs((prob_home + prob_draw + prob_away) - 1.0) < 1e-9
    assert 0.0 <= prob_home <= 1.0
    assert prob_home == max(prob_home, prob_draw, prob_away)

    away_probs = model.predict_proba(_features(0.5, 3.0))
    assert away_probs[2] == max(away_probs)


def test_predict_handles_missing_and_none_features() -> None:
    model = LogisticMatchModel(max_iter=2000).fit(_training_set())

    sparse: dict[str, float | int | None] = {"home_points_per_match_last_5": None}
    probs = model.predict_proba(sparse)
    assert abs(sum(probs) - 1.0) < 1e-9


def test_fit_requires_enough_samples_and_outcomes() -> None:
    with pytest.raises(ValueError, match="at least 3 training samples"):
        LogisticMatchModel().fit(
            [MatchFeatureSample(features=_features(1.0, 1.0), outcome="H")]
        )

    single_outcome = [
        MatchFeatureSample(features=_features(1.0, 1.0), outcome="H") for _ in range(5)
    ]
    with pytest.raises(ValueError, match="two distinct outcomes"):
        LogisticMatchModel().fit(single_outcome)


def test_predict_before_fit_raises() -> None:
    with pytest.raises(ValueError, match="must be fitted"):
        LogisticMatchModel().predict_proba(_features(1.0, 1.0))

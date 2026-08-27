from __future__ import annotations

import pytest

from futpredict.evaluation.rps import ranked_probability_score


def test_rps_perfect_prediction_is_zero() -> None:
    assert ranked_probability_score((1.0, 0.0, 0.0), "H") == 0.0


def test_rps_uniform_home_result() -> None:
    assert ranked_probability_score((1 / 3, 1 / 3, 1 / 3), "H") == pytest.approx(5 / 18)


def test_rps_rejects_probabilities_that_do_not_sum_to_one() -> None:
    with pytest.raises(ValueError, match="sum to 1"):
        ranked_probability_score((0.8, 0.2, 0.2), "H")

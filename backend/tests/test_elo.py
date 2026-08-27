from __future__ import annotations

from futpredict.models.elo import EloConfig, actual_home_score, update_elo


def test_actual_home_score() -> None:
    assert actual_home_score(2, 1) == 1.0
    assert actual_home_score(1, 1) == 0.5
    assert actual_home_score(0, 1) == 0.0


def test_update_elo_is_zero_sum() -> None:
    home_after, away_after = update_elo(
        1500.0,
        1500.0,
        2,
        1,
        EloConfig(k=20.0, home_advantage=0.0, goal_difference_factor=False),
    )
    assert home_after == 1510.0
    assert away_after == 1490.0
    assert home_after + away_after == 3000.0

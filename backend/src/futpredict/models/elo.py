from __future__ import annotations

from dataclasses import dataclass
from math import log


@dataclass(frozen=True)
class EloConfig:
    k: float = 20.0
    home_advantage: float = 65.0
    goal_difference_factor: bool = True


def expected_home_score(
    home_rating: float,
    away_rating: float,
    home_advantage: float = 65.0,
) -> float:
    expected: float = 1.0 / (
        1.0 + 10.0 ** ((away_rating - home_rating - home_advantage) / 400.0)
    )
    return expected


def actual_home_score(home_goals: int, away_goals: int) -> float:
    if home_goals > away_goals:
        return 1.0
    if home_goals == away_goals:
        return 0.5
    return 0.0


def goal_multiplier(home_goals: int, away_goals: int) -> float:
    goal_diff = abs(home_goals - away_goals)
    if goal_diff <= 1:
        return 1.0
    return 1.0 + log(goal_diff)


def update_elo(
    home_rating: float,
    away_rating: float,
    home_goals: int,
    away_goals: int,
    config: EloConfig | None = None,
) -> tuple[float, float]:
    cfg = config or EloConfig()
    expected = expected_home_score(home_rating, away_rating, cfg.home_advantage)
    actual = actual_home_score(home_goals, away_goals)
    multiplier = goal_multiplier(home_goals, away_goals) if cfg.goal_difference_factor else 1.0
    adjustment = cfg.k * multiplier * (actual - expected)
    return home_rating + adjustment, away_rating - adjustment

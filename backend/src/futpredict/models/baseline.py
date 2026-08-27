from __future__ import annotations


def always_home_probabilities() -> tuple[float, float, float]:
    return (1.0, 0.0, 0.0)


def uniform_probabilities() -> tuple[float, float, float]:
    return (1.0 / 3.0, 1.0 / 3.0, 1.0 / 3.0)


def historical_frequency_probabilities(
    home_wins: int,
    draws: int,
    away_wins: int,
) -> tuple[float, float, float]:
    total = home_wins + draws + away_wins
    if total <= 0:
        return uniform_probabilities()
    return (home_wins / total, draws / total, away_wins / total)

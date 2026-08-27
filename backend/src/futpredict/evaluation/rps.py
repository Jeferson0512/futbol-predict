from __future__ import annotations

from collections.abc import Sequence

OUTCOMES = ("H", "D", "A")


def outcome_vector(outcome: str) -> tuple[float, float, float]:
    normalized = outcome.upper()
    if normalized not in OUTCOMES:
        msg = f"outcome must be one of {OUTCOMES}, got {outcome!r}"
        raise ValueError(msg)
    return (
        1.0 if normalized == "H" else 0.0,
        1.0 if normalized == "D" else 0.0,
        1.0 if normalized == "A" else 0.0,
    )


def ranked_probability_score(
    probabilities: Sequence[float],
    actual: str | Sequence[float],
) -> float:
    if len(probabilities) != 3:
        msg = "RPS for 1X2 needs exactly 3 probabilities"
        raise ValueError(msg)

    actual_vector = outcome_vector(actual) if isinstance(actual, str) else tuple(actual)
    if len(actual_vector) != 3:
        msg = "RPS for 1X2 needs exactly 3 actual values"
        raise ValueError(msg)

    total_probability = sum(probabilities)
    if any(prob < 0 for prob in probabilities) or abs(total_probability - 1.0) > 1e-6:
        msg = "probabilities must be non-negative and sum to 1"
        raise ValueError(msg)

    cumulative_error = 0.0
    for index in range(2):
        predicted_cdf = sum(probabilities[: index + 1])
        actual_cdf = sum(actual_vector[: index + 1])
        cumulative_error += (predicted_cdf - actual_cdf) ** 2

    return cumulative_error / 2.0


def mean_rps(rows: Sequence[tuple[Sequence[float], str]]) -> float:
    if not rows:
        raise ValueError("cannot compute mean RPS for an empty collection")
    total = sum(ranked_probability_score(probabilities, actual) for probabilities, actual in rows)
    return total / len(rows)

from __future__ import annotations

from collections.abc import Sequence
from math import log

from futpredict.evaluation.rps import outcome_vector


def log_loss(probabilities: Sequence[float], actual: str, epsilon: float = 1e-15) -> float:
    vector = outcome_vector(actual)
    actual_index = vector.index(1.0)
    probability = min(max(probabilities[actual_index], epsilon), 1.0 - epsilon)
    return -log(probability)


def brier_score(probabilities: Sequence[float], actual: str) -> float:
    vector = outcome_vector(actual)
    pairs = zip(probabilities, vector, strict=True)
    return sum((probability - observed) ** 2 for probability, observed in pairs)


def accuracy(probabilities: Sequence[float], actual: str) -> float:
    labels = ("H", "D", "A")
    predicted = labels[max(range(len(probabilities)), key=lambda index: probabilities[index])]
    return 1.0 if predicted == actual.upper() else 0.0

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from futpredict.domain.matches import MatchResult, result_from_goals
from futpredict.models.poisson import (
    DIXON_COLES_MODEL_NAME,
    MIN_TRAIN_MATCHES,
    DixonColesMatchModel,
    GoalSample,
    goal_samples_from_matches,
)

_START = datetime(2024, 1, 1, tzinfo=UTC)
_TEAMS = ("Alpha", "Beta", "Gamma", "Delta", "Epsilon", "Zeta")


def _samples(count: int = 120) -> list[GoalSample]:
    """Liga sintetica con jerarquia clara: Alpha marca mas, Zeta encaja mas."""
    strength = {team: index for index, team in enumerate(_TEAMS)}
    samples: list[GoalSample] = []
    index = 0
    while len(samples) < count:
        for home in _TEAMS:
            for away in _TEAMS:
                if home == away or len(samples) >= count:
                    continue
                samples.append(
                    GoalSample(
                        home_team=home,
                        away_team=away,
                        # Los mejores (indice bajo) marcan mas y encajan menos.
                        home_goals=3 - min(strength[home], 2),
                        away_goals=min(strength[away], 2),
                        kickoff_utc=_START + timedelta(days=index),
                    )
                )
                index += 1
    return samples


def _match(home: str, away: str, home_goals: int, away_goals: int, day: int) -> MatchResult:
    return MatchResult(
        kickoff_utc=_START + timedelta(days=day),
        season="2024",
        division="TEST",
        home_team=home,
        away_team=away,
        home_goals=home_goals,
        away_goals=away_goals,
        outcome=result_from_goals(home_goals, away_goals),
    )


def test_fit_requires_minimum_matches() -> None:
    with pytest.raises(ValueError, match="al menos"):
        DixonColesMatchModel().fit(_samples(MIN_TRAIN_MATCHES - 1))


def test_predict_before_fit_raises() -> None:
    with pytest.raises(ValueError, match="no esta ajustado"):
        DixonColesMatchModel().predict_proba("Alpha", "Beta")


def test_predict_proba_returns_normalized_distribution() -> None:
    model = DixonColesMatchModel().fit(_samples())

    probabilities = model.predict_proba("Alpha", "Beta")

    assert probabilities is not None
    assert len(probabilities) == 3
    assert all(0.0 <= value <= 1.0 for value in probabilities)
    assert sum(probabilities) == pytest.approx(1.0)


def test_stronger_home_team_gets_more_probability() -> None:
    model = DixonColesMatchModel().fit(_samples())

    fuerte = model.predict_proba("Alpha", "Zeta")
    debil = model.predict_proba("Zeta", "Alpha")

    assert fuerte is not None
    assert debil is not None
    # Alpha domina a Zeta: como local debe ganar mas probabilidad que al reves.
    assert fuerte[0] > debil[0]


def test_unknown_team_returns_none() -> None:
    model = DixonColesMatchModel().fit(_samples())

    # Un recien ascendido no estuvo en el entrenamiento: se omite en vez de
    # inventar una prediccion, igual que market_avg_odds cuando falta la cuota.
    assert model.predict_proba("Recien Ascendido", "Alpha") is None
    assert model.predict_proba("Alpha", "Recien Ascendido") is None


def test_same_team_returns_none() -> None:
    model = DixonColesMatchModel().fit(_samples())

    assert model.predict_proba("Alpha", "Alpha") is None


def test_predict_many_keeps_order_and_gaps() -> None:
    model = DixonColesMatchModel().fit(_samples())

    results = model.predict_many(
        [("Alpha", "Beta"), ("Desconocido", "Beta"), ("Gamma", "Delta")]
    )

    assert len(results) == 3
    assert results[0] is not None
    assert results[1] is None
    assert results[2] is not None


def test_predict_many_on_empty_input() -> None:
    model = DixonColesMatchModel().fit(_samples())

    assert model.predict_many([]) == []


def test_predict_many_matches_predict_proba() -> None:
    model = DixonColesMatchModel().fit(_samples())

    uno = model.predict_proba("Alpha", "Beta")
    lote = model.predict_many([("Alpha", "Beta")])[0]

    assert uno is not None
    assert lote is not None
    assert uno == pytest.approx(lote)


def test_known_teams_exposes_training_roster() -> None:
    model = DixonColesMatchModel().fit(_samples())

    assert model.known_teams == frozenset(_TEAMS)


def test_goal_samples_from_matches_converts_results() -> None:
    matches = [_match("Alpha", "Beta", 2, 1, 0), _match("Beta", "Gamma", 0, 0, 1)]

    samples = goal_samples_from_matches(matches)

    assert [(s.home_team, s.home_goals, s.away_goals) for s in samples] == [
        ("Alpha", 2, 1),
        ("Beta", 0, 0),
    ]


def test_goal_samples_skips_matches_without_score() -> None:
    played = _match("Alpha", "Beta", 2, 1, 0)
    pending = MatchResult(
        kickoff_utc=_START,
        season="2024",
        division="TEST",
        home_team="Gamma",
        away_team="Delta",
        home_goals=None,  # type: ignore[arg-type]
        away_goals=None,  # type: ignore[arg-type]
        outcome="H",
    )

    samples = goal_samples_from_matches([played, pending])

    assert len(samples) == 1
    assert samples[0].home_team == "Alpha"


def test_model_name_is_stable() -> None:
    # El nombre viaja a model_versions y a la app: cambiarlo rompe el historico.
    assert DIXON_COLES_MODEL_NAME == "dixon_coles"

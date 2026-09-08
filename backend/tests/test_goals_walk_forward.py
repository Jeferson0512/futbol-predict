from __future__ import annotations

import zlib
from datetime import UTC, datetime, timedelta

import numpy as np
import pytest

from futpredict.domain.matches import MatchResult, result_from_goals
from futpredict.evaluation.goals_walk_forward import (
    run_configured_goal_walk_forward,
    run_goal_model_walk_forward,
)
from futpredict.models.poisson import (
    DIXON_COLES_MODEL_NAME,
    DixonColesMatchModel,
    GoalSample,
    goal_samples_from_matches,
)

# 10 equipos -> 90 partidos por temporada. Con 6 equipos (30 partidos) el
# ruido de muestreo dominaba y el test medía la suerte del sorteo.
_TEAMS = (
    "Alpha", "Beta", "Gamma", "Delta", "Epsilon",
    "Zeta", "Eta", "Theta", "Iota", "Kappa",
)
_SEASONS = ("2021", "2022", "2023", "2024")


def _season_matches(season: str, division: str = "TEST") -> list[MatchResult]:
    """Una temporada de ida y vuelta entre 10 equipos (90 partidos).

    Cada equipo tiene UNA fuerza latente que gobierna a la vez lo que marca y lo
    que encaja. Los goles se sortean Poisson alrededor de esa fuerza con semilla
    fija: hace falta varianza real o el ajuste de maxima verosimilitud degenera,
    y hace falta que sea reproducible para que el test no sea intermitente.
    """
    # crc32, no hash(): el hash de strings de Python esta aleatorizado por
    # proceso (PYTHONHASHSEED) y haria el test intermitente.
    rng = np.random.default_rng(zlib.crc32(f"{season}:{division}".encode()))
    start = datetime(int(season), 2, 1, tzinfo=UTC)
    # Alpha es el mejor (2.52), Kappa el peor (0.0).
    strength = {team: (len(_TEAMS) - 1 - index) * 0.28 for index, team in enumerate(_TEAMS)}
    matches: list[MatchResult] = []
    day = 0
    for home in _TEAMS:
        for away in _TEAMS:
            if home == away:
                continue
            edge = strength[home] - strength[away]
            home_goals = int(rng.poisson(max(0.15, 1.4 + 0.45 * edge)))
            away_goals = int(rng.poisson(max(0.15, 1.1 - 0.45 * edge)))
            matches.append(
                MatchResult(
                    kickoff_utc=start + timedelta(days=day),
                    season=season,
                    division=division,
                    home_team=home,
                    away_team=away,
                    home_goals=home_goals,
                    away_goals=away_goals,
                    outcome=result_from_goals(home_goals, away_goals),
                )
            )
            day += 1
    return matches


def _all_matches(division: str = "TEST") -> list[MatchResult]:
    return [match for season in _SEASONS for match in _season_matches(season, division)]


def test_walk_forward_produces_one_window_per_evaluation_season() -> None:
    metrics = run_goal_model_walk_forward(
        _all_matches(),
        start_season=_SEASONS[0],
        end_season=_SEASONS[-1],
        initial_train_seasons=2,
        seasons=list(_SEASONS),
    )

    # 4 temporadas, 2 de entrenamiento inicial -> 2 ventanas de evaluacion.
    assert [metric.evaluation_season for metric in metrics] == ["2023", "2024"]
    assert all(metric.summary.model == DIXON_COLES_MODEL_NAME for metric in metrics)
    assert all(metric.division == "TEST" for metric in metrics)


def test_walk_forward_never_trains_on_the_evaluated_season() -> None:
    metrics = run_goal_model_walk_forward(
        _all_matches(),
        start_season=_SEASONS[0],
        end_season=_SEASONS[-1],
        initial_train_seasons=2,
        seasons=list(_SEASONS),
    )

    for metric in metrics:
        # La regla dura del proyecto: el entrenamiento cierra antes de que
        # empiece la temporada evaluada.
        assert metric.train_end_season < metric.evaluation_season
        assert metric.train_window_end_utc < metric.eval_window_start_utc


def test_walk_forward_separates_divisions() -> None:
    matches = [*_all_matches("LIGA_A"), *_all_matches("LIGA_B")]

    metrics = run_goal_model_walk_forward(
        matches,
        start_season=_SEASONS[0],
        end_season=_SEASONS[-1],
        initial_train_seasons=2,
        seasons=list(_SEASONS),
    )

    assert {metric.division for metric in metrics} == {"LIGA_A", "LIGA_B"}
    assert len(metrics) == 4


def test_walk_forward_skips_windows_without_enough_training() -> None:
    metrics = run_goal_model_walk_forward(
        _all_matches(),
        start_season=_SEASONS[0],
        end_season=_SEASONS[-1],
        initial_train_seasons=2,
        seasons=list(_SEASONS),
        # Ninguna ventana llega a este minimo: no se debe inventar un ajuste.
        min_train_matches=10_000,
    )

    assert metrics == []


def test_walk_forward_requires_an_evaluation_season() -> None:
    with pytest.raises(ValueError, match="at least one evaluation season"):
        run_goal_model_walk_forward(
            _all_matches(),
            start_season=_SEASONS[0],
            end_season=_SEASONS[-1],
            initial_train_seasons=len(_SEASONS),
            seasons=list(_SEASONS),
        )


def test_walk_forward_rejects_non_positive_training_seasons() -> None:
    with pytest.raises(ValueError, match="must be positive"):
        run_goal_model_walk_forward(
            _all_matches(),
            start_season=_SEASONS[0],
            end_season=_SEASONS[-1],
            initial_train_seasons=0,
            seasons=list(_SEASONS),
        )


def test_metrics_carry_usable_rps() -> None:
    metrics = run_goal_model_walk_forward(
        _all_matches(),
        start_season=_SEASONS[0],
        end_season=_SEASONS[-1],
        initial_train_seasons=2,
        seasons=list(_SEASONS),
    )

    for metric in metrics:
        assert metric.summary.n_matches > 0
        assert 0.0 <= metric.summary.rps <= 1.0
        # La liga tiene una jerarquia real, asi que el modelo debe quedar por
        # debajo de historical_frequency (~0.25) y del azar (~0.22). No se le
        # exige mas: el umbral mide que aprende, no que sea el mejor modelo.
        assert metric.summary.rps < 0.22
        assert metric.summary.accuracy > 0.55


def test_configured_runner_supports_several_models() -> None:
    def factory() -> DixonColesMatchModel:
        return DixonColesMatchModel(decay_xi=0.0)

    metrics = run_configured_goal_walk_forward(
        _all_matches(),
        start_season=_SEASONS[0],
        end_season=_SEASONS[-1],
        initial_train_seasons=2,
        seasons=list(_SEASONS),
        models=((DixonColesMatchModel, DIXON_COLES_MODEL_NAME), (factory, "dixon_coles_sin_decay")),
    )

    assert {metric.summary.model for metric in metrics} == {
        DIXON_COLES_MODEL_NAME,
        "dixon_coles_sin_decay",
    }


def test_decay_weighs_recent_seasons_more() -> None:
    """Con decaimiento, una temporada reciente que invierte la jerarquia pesa mas."""
    historico = [
        sample
        for season in ("2021", "2022", "2023")
        for sample in goal_samples_from_matches(_season_matches(season))
    ]
    # 2024 con los papeles cambiados: el peor equipo golea al mejor.
    reciente = [
        GoalSample(
            home_team=sample.away_team,
            away_team=sample.home_team,
            home_goals=sample.home_goals,
            away_goals=sample.away_goals,
            kickoff_utc=sample.kickoff_utc,
        )
        for sample in goal_samples_from_matches(_season_matches("2024"))
    ]
    samples = [*historico, *reciente]

    con_decay = DixonColesMatchModel(decay_xi=0.01).fit(samples).predict_proba("Zeta", "Alpha")
    sin_decay = DixonColesMatchModel(decay_xi=0.0).fit(samples).predict_proba("Zeta", "Alpha")

    assert con_decay is not None
    assert sin_decay is not None
    # Zeta (historicamente el peor) viene de dominar: con decaimiento el modelo
    # le debe dar mas probabilidad de ganar que ignorando el orden temporal.
    assert con_decay[0] > sin_decay[0]


def test_degenerate_fit_returns_none_instead_of_raising() -> None:
    """Un ajuste imposible se omite, no tumba el pipeline ni el API."""
    start = datetime(2024, 1, 1, tzinfo=UTC)
    # Dos equipos y siempre el mismo marcador: verosimilitud sin varianza.
    samples = [
        GoalSample("Alpha", "Beta", 1, 1, start + timedelta(days=index)) for index in range(60)
    ]

    model = DixonColesMatchModel().fit(samples)

    assert model.predict_proba("Alpha", "Beta") is None

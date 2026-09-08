from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from futpredict.data.altitude import (
    ALTITUDE_BY_DIVISION,
    PERU_TEAM_ALTITUDE_M,
    altitude_coverage,
    altitude_gap_m,
    division_has_altitude,
    team_altitude_m,
)
from futpredict.domain.matches import MatchResult, result_from_goals
from futpredict.evaluation.altitude_walk_forward import (
    predict_sequence,
    run_altitude_elo_walk_forward,
)
from futpredict.models.altitude_elo import (
    ALTITUDE_ELO_MODEL_NAME,
    AltitudeEloConfig,
    AltitudeEloModel,
    home_advantage_for_gap,
)

_START = datetime(2024, 2, 1, tzinfo=UTC)


def _match(
    home: str,
    away: str,
    home_goals: int = 1,
    away_goals: int = 0,
    day: int = 0,
    division: str = "PER1",
    season: str = "2024",
) -> MatchResult:
    return MatchResult(
        # La fecha sigue a la temporada: si no, las ventanas walk-forward se
        # solapan en el tiempo y el test no comprobaria nada temporal.
        kickoff_utc=datetime(int(season), 2, 1, tzinfo=UTC) + timedelta(days=day),
        season=season,
        division=division,
        home_team=home,
        away_team=away,
        home_goals=home_goals,
        away_goals=away_goals,
        outcome=result_from_goals(home_goals, away_goals),
    )


# --- tabla de altitudes -----------------------------------------------------


def test_altitude_gap_is_absolute() -> None:
    # El efecto medido es simetrico: viajar a otra altitud perjudica en las dos
    # direcciones, asi que el desnivel se usa en modulo.
    subiendo = altitude_gap_m("Cusco FC", "Alianza Lima", "PER1")
    bajando = altitude_gap_m("Alianza Lima", "Cusco FC", "PER1")

    assert subiendo == bajando
    assert subiendo == 3399 - 154


def test_altitude_gap_is_zero_for_same_city() -> None:
    assert altitude_gap_m("Alianza Lima", "Universitario", "PER1") == 0


def test_altitude_gap_none_for_unknown_team() -> None:
    assert altitude_gap_m("Equipo Nuevo", "Alianza Lima", "PER1") is None


def test_altitude_gap_none_for_division_without_table() -> None:
    assert altitude_gap_m("Arsenal", "Chelsea", "E0") is None
    assert team_altitude_m("Arsenal", "E0") is None


def test_division_has_altitude() -> None:
    assert division_has_altitude("PER1") is True
    assert division_has_altitude("E0") is False
    assert division_has_altitude("BRA1") is False


def test_altitude_table_values_are_plausible() -> None:
    for team, metres in PERU_TEAM_ALTITUDE_M.items():
        # Peru va del nivel del mar a Juliaca (3.825 m); fuera de ese rango
        # seria un error de tipeo, no una sede real.
        assert 0 <= metres <= 4200, team


def test_altitude_coverage_reports_missing_teams() -> None:
    pairs = [
        ("Alianza Lima", "Cusco FC", "PER1"),
        ("Equipo Nuevo", "Cusco FC", "PER1"),
        ("Arsenal", "Chelsea", "E0"),  # division sin tabla: no cuenta
    ]

    known, total, missing = altitude_coverage(pairs)

    assert (known, total) == (1, 2)
    assert missing == ["Equipo Nuevo"]


def test_every_division_with_altitude_is_declared() -> None:
    assert set(ALTITUDE_BY_DIVISION) == {"PER1"}


# --- ventaja local ----------------------------------------------------------


def test_home_advantage_grows_with_gap() -> None:
    config = AltitudeEloConfig()

    plano = home_advantage_for_gap(0, config)
    medio = home_advantage_for_gap(1500, config)
    alto = home_advantage_for_gap(3400, config)

    assert plano == config.base_home_advantage
    assert plano < medio < alto


def test_home_advantage_is_capped() -> None:
    config = AltitudeEloConfig(max_gap_km=3.0)

    tope = home_advantage_for_gap(3000, config)
    exceso = home_advantage_for_gap(9000, config)

    # Sin tope, un desnivel absurdo daria una ventaja absurda.
    assert tope == exceso


def test_home_advantage_without_altitude_is_the_base() -> None:
    config = AltitudeEloConfig()

    assert home_advantage_for_gap(None, config) == config.base_home_advantage


# --- modelo -----------------------------------------------------------------


def test_probabilities_sum_to_one() -> None:
    model = AltitudeEloModel()

    probabilities = model.predict_proba(_match("Cusco FC", "Alianza Lima"))

    assert sum(probabilities) == pytest.approx(1.0)


def test_altitude_gap_favours_the_home_team() -> None:
    model = AltitudeEloModel()

    # Mismo rating inicial en ambos: la unica diferencia es el desnivel.
    con_desnivel = model.predict_proba(_match("Cusco FC", "Alianza Lima"))
    sin_desnivel = model.predict_proba(_match("Alianza Lima", "Universitario"))

    assert con_desnivel[0] > sin_desnivel[0]
    assert con_desnivel[2] < sin_desnivel[2]


def test_zero_coefficient_reproduces_plain_elo() -> None:
    """Control: sin coeficiente el modelo debe ser identico a `elo_simple`."""
    plano = AltitudeEloModel(AltitudeEloConfig(advantage_per_km=0.0))

    alto = plano.predict_proba(_match("Cusco FC", "Alianza Lima"))
    llano = plano.predict_proba(_match("Alianza Lima", "Universitario"))

    assert alto == pytest.approx(llano)


def test_division_without_table_gets_base_advantage() -> None:
    model = AltitudeEloModel()

    ingles = model.predict_proba(_match("Arsenal", "Chelsea", division="E0"))
    peruano_llano = model.predict_proba(_match("Alianza Lima", "Universitario"))

    # Sin altitudes conocidas cae exactamente en el Elo de siempre.
    assert ingles == pytest.approx(peruano_llano)


def test_observe_updates_ratings() -> None:
    model = AltitudeEloModel()
    antes = model.rating("PER1", "Cusco FC")

    model.observe(_match("Cusco FC", "Alianza Lima", 3, 0))

    assert model.rating("PER1", "Cusco FC") > antes
    assert model.rating("PER1", "Alianza Lima") < antes


def test_ratings_do_not_leak_across_divisions() -> None:
    model = AltitudeEloModel()

    model.observe(_match("Cusco FC", "Alianza Lima", 5, 0))

    # Un equipo homonimo en otra liga no hereda el rating.
    assert model.rating("E0", "Cusco FC") == model.config.initial_rating


# --- walk-forward -----------------------------------------------------------


def _season(season: str, teams: tuple[str, ...]) -> list[MatchResult]:
    matches: list[MatchResult] = []
    day = 0
    for home in teams:
        for away in teams:
            if home == away:
                continue
            matches.append(_match(home, away, 2, 1, day=day, season=season))
            day += 1
    return matches


_TEAMS = ("Cusco FC", "Alianza Lima", "Sport Huancayo", "Sport Boys", "Melgar", "Universitario")
_SEASONS = ("2021", "2022", "2023", "2024")


def test_predict_sequence_uses_state_before_the_kickoff_block() -> None:
    """Partidos del mismo kickoff no pueden filtrarse informacion entre si."""
    model = AltitudeEloModel()
    # El MISMO emparejamiento dos veces en la misma fecha: mismo desnivel y
    # mismos rivales, asi que cualquier diferencia solo puede venir de que el
    # primer resultado se colo en la segunda prediccion.
    simultaneos = [
        _match("Cusco FC", "Alianza Lima", 5, 0, day=0),
        _match("Cusco FC", "Alianza Lima", 0, 0, day=0),
    ]

    rows = predict_sequence(model, simultaneos)

    assert rows[0].probabilities == pytest.approx(rows[1].probabilities)

    # Y despues del bloque los ratings si deben haberse movido.
    assert model.rating("PER1", "Cusco FC") > model.config.initial_rating


def test_predict_sequence_applies_results_between_kickoffs() -> None:
    """Entre fechas distintas el modelo si debe aprender del resultado."""
    model = AltitudeEloModel()
    consecutivos = [
        _match("Cusco FC", "Alianza Lima", 5, 0, day=0),
        _match("Cusco FC", "Alianza Lima", 0, 0, day=1),
    ]

    rows = predict_sequence(model, consecutivos)

    # La goleada del dia 0 sube a Cusco: el dia 1 debe salir mas favorito.
    assert rows[1].probabilities[0] > rows[0].probabilities[0]


def test_walk_forward_produces_expected_windows() -> None:
    matches = [m for season in _SEASONS for m in _season(season, _TEAMS)]

    metrics = run_altitude_elo_walk_forward(
        matches,
        start_season=_SEASONS[0],
        end_season=_SEASONS[-1],
        initial_train_seasons=2,
        seasons=list(_SEASONS),
    )

    assert [m.evaluation_season for m in metrics] == ["2023", "2024"]
    assert all(m.summary.model == ALTITUDE_ELO_MODEL_NAME for m in metrics)
    for metric in metrics:
        assert metric.train_end_season < metric.evaluation_season
        assert metric.train_window_end_utc < metric.eval_window_start_utc


def test_walk_forward_requires_an_evaluation_season() -> None:
    matches = [m for season in _SEASONS for m in _season(season, _TEAMS)]

    with pytest.raises(ValueError, match="at least one evaluation season"):
        run_altitude_elo_walk_forward(
            matches,
            start_season=_SEASONS[0],
            end_season=_SEASONS[-1],
            initial_train_seasons=len(_SEASONS),
            seasons=list(_SEASONS),
        )


def test_walk_forward_predicts_every_match() -> None:
    """A diferencia de Dixon-Coles, Elo no omite equipos que no vio antes."""
    matches = [m for season in _SEASONS for m in _season(season, _TEAMS)]

    metrics = run_altitude_elo_walk_forward(
        matches,
        start_season=_SEASONS[0],
        end_season=_SEASONS[-1],
        initial_train_seasons=2,
        seasons=list(_SEASONS),
    )

    por_temporada = len(_TEAMS) * (len(_TEAMS) - 1)
    assert all(metric.summary.n_matches == por_temporada for metric in metrics)


def test_model_name_is_stable() -> None:
    # Viaja a model_versions y a la app: cambiarlo rompe el historico.
    assert ALTITUDE_ELO_MODEL_NAME == "elo_altitude"

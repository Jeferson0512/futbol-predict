"""Elo con ventaja local ajustada por desnivel de altitud.

`elo_simple` usa una ventaja local fija de 65 puntos para las 8 ligas. En Liga 1
eso deja fuera el factor mas fuerte del torneo: cuando las sedes se separan mas
de 3.000 m, el local pasa de ganar el 42.9% al 59.1% de los partidos (ver
`data/altitude.py`). Este modelo mantiene el Elo tal cual y solo hace variable
la ventaja local:

    ventaja_local = base + por_km * min(|desnivel_km|, tope_km)

Cuando no se conoce la altitud de alguna de las sedes, cae exactamente en
`elo_simple`: sin datos no inventa ventaja.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from futpredict.data.altitude import altitude_gap_m
from futpredict.domain.matches import MatchResult
from futpredict.models.elo import EloConfig, expected_home_score, update_elo

ALTITUDE_ELO_MODEL_NAME = "elo_altitude"
DEFAULT_INITIAL_RATING = 1500.0
# Misma probabilidad de empate que usa `elo_simple` en el backtest: aisla el
# efecto de la altitud en vez de mezclarlo con otro cambio.
DRAW_PROBABILITY = 0.26


@dataclass(frozen=True)
class AltitudeEloConfig:
    """Parametros del ajuste por altitud.

    `advantage_per_km` y `max_gap_km` se eligen sobre temporadas de
    entrenamiento, nunca sobre las que se evaluan.
    """

    elo: EloConfig = EloConfig()
    base_home_advantage: float = 65.0
    # Elegidos por rejilla sobre 2021-2023 (temporadas de entrenamiento) y
    # evaluados aparte en 2024-2026: RPS 0.1893 vs 0.1974 de elo_simple.
    advantage_per_km: float = 60.0
    max_gap_km: float = 4.0
    initial_rating: float = DEFAULT_INITIAL_RATING


def home_advantage_for_gap(gap_m: int | None, config: AltitudeEloConfig) -> float:
    """Ventaja local en puntos Elo para un desnivel dado."""
    if gap_m is None:
        return config.base_home_advantage
    gap_km = min(abs(gap_m) / 1000.0, config.max_gap_km)
    return config.base_home_advantage + config.advantage_per_km * gap_km


class AltitudeEloModel:
    """Elo secuencial con ventaja local variable segun el desnivel.

    Es secuencial, no entrenado por ventanas: se le pasan los partidos en orden
    y para cada uno predice ANTES de aplicar el resultado. `observe` separa
    ambos momentos para que quien lo use no pueda colar el resultado en la
    prediccion.
    """

    def __init__(self, config: AltitudeEloConfig | None = None) -> None:
        self.config = config or AltitudeEloConfig()
        self._ratings: dict[tuple[str, str], float] = {}

    def rating(self, division: str, team: str) -> float:
        return self._ratings.get((division, team), self.config.initial_rating)

    def predict_proba(self, match: MatchResult) -> tuple[float, float, float]:
        gap = altitude_gap_m(match.home_team, match.away_team, match.division)
        advantage = home_advantage_for_gap(gap, self.config)
        home_expected = expected_home_score(
            self.rating(match.division, match.home_team),
            self.rating(match.division, match.away_team),
            advantage,
        )
        decisive = 1.0 - DRAW_PROBABILITY
        return (
            home_expected * decisive,
            DRAW_PROBABILITY,
            (1.0 - home_expected) * decisive,
        )

    def observe(self, match: MatchResult) -> None:
        """Aplica el resultado de un partido ya predicho."""
        home_key = (match.division, match.home_team)
        away_key = (match.division, match.away_team)
        new_home, new_away = update_elo(
            self._ratings.get(home_key, self.config.initial_rating),
            self._ratings.get(away_key, self.config.initial_rating),
            match.home_goals,
            match.away_goals,
            self.config.elo,
        )
        self._ratings[home_key] = new_home
        self._ratings[away_key] = new_away

    def fit(self, matches: Sequence[MatchResult]) -> AltitudeEloModel:
        """Consume partidos historicos para dejar los ratings al dia."""
        for match in sorted(matches, key=lambda item: item.kickoff_utc):
            self.observe(match)
        return self

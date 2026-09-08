"""Modelo de goles Dixon-Coles sobre `penaltyblog`.

Es una familia distinta a la de los tabulares (`models/tabular.py`): en vez de
aprender de features rodantes, estima una **fuerza de ataque y de defensa por
equipo** mas una ventaja local, y de ahi saca la matriz de marcadores. El 1X2
es la suma de esa matriz, asi que el mismo ajuste da tambien marcador exacto y
over/under.

Dos rasgos lo separan de un Poisson plano:

- **Correccion de dependencia** en los marcadores bajos (0-0, 1-0, 0-1, 1-1),
  donde el Poisson independiente subestima empates.
- **Decaimiento temporal**: los partidos viejos pesan menos (`xi`), asi el
  modelo sigue la forma reciente sin dejar de usar el historico.

Interesa sobre todo en las ligas sin cuotas (Peru, Brasil, Argentina), donde no
hay `market_avg_odds` que marque el techo.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

DIXON_COLES_MODEL_NAME = "dixon_coles"
# xi=0.0018 es el valor de referencia de penaltyblog: vida media ~1 ano.
DEFAULT_DECAY_XI = 0.0018
DEFAULT_MAX_GOALS = 15
MIN_TRAIN_MATCHES = 50


@dataclass(frozen=True)
class GoalSample:
    """Un partido terminado, visto como marcador."""

    home_team: str
    away_team: str
    home_goals: int
    away_goals: int
    kickoff_utc: datetime


class DixonColesMatchModel:
    """Ajusta Dixon-Coles y devuelve probabilidades 1X2.

    `predict_proba` devuelve `None` cuando alguno de los equipos no estuvo en el
    entrenamiento (un recien ascendido, por ejemplo). Es el mismo criterio que
    usa `market_avg_odds` cuando falta la cuota: se omite la prediccion en vez
    de inventarla.
    """

    def __init__(
        self,
        *,
        decay_xi: float = DEFAULT_DECAY_XI,
        max_goals: int = DEFAULT_MAX_GOALS,
    ) -> None:
        self.decay_xi = decay_xi
        self.max_goals = max_goals
        self._model: Any | None = None
        self._known_teams: frozenset[str] = frozenset()

    @property
    def known_teams(self) -> frozenset[str]:
        return self._known_teams

    def fit(self, samples: Sequence[GoalSample]) -> DixonColesMatchModel:
        if len(samples) < MIN_TRAIN_MATCHES:
            msg = f"se necesitan al menos {MIN_TRAIN_MATCHES} partidos para ajustar Dixon-Coles"
            raise ValueError(msg)

        from penaltyblog.models import DixonColesGoalModel, dixon_coles_weights

        ordered = sorted(samples, key=lambda sample: sample.kickoff_utc)
        home_teams = [sample.home_team for sample in ordered]
        away_teams = [sample.away_team for sample in ordered]
        home_goals = [sample.home_goals for sample in ordered]
        away_goals = [sample.away_goals for sample in ordered]
        # El decaimiento se calcula contra el ultimo partido de entrenamiento,
        # no contra "hoy": mantiene el walk-forward reproducible.
        weights = dixon_coles_weights(
            [sample.kickoff_utc for sample in ordered],
            xi=self.decay_xi,
            base_date=ordered[-1].kickoff_utc,
        )

        model = DixonColesGoalModel(home_goals, away_goals, home_teams, away_teams, weights)
        model.fit()
        self._model = model
        self._known_teams = frozenset(home_teams) | frozenset(away_teams)
        return self

    def predict_proba(self, home_team: str, away_team: str) -> tuple[float, float, float] | None:
        results = self.predict_many([(home_team, away_team)])
        return results[0]

    def predict_many(
        self,
        pairs: Sequence[tuple[str, str]],
    ) -> list[tuple[float, float, float] | None]:
        """Predice en lote: es ordenes de magnitud mas rapido que uno a uno."""
        if self._model is None:
            msg = "el modelo no esta ajustado; llama a fit() primero"
            raise ValueError(msg)
        if not pairs:
            return []

        known = self._known_teams
        predictable = [
            index
            for index, (home, away) in enumerate(pairs)
            if home in known and away in known and home != away
        ]
        results: list[tuple[float, float, float] | None] = [None] * len(pairs)
        if not predictable:
            return results

        try:
            grids = self._model.predict_many(
                [pairs[index][0] for index in predictable],
                [pairs[index][1] for index in predictable],
                max_goals=self.max_goals,
            )
        except (ValueError, FloatingPointError):
            # Un ajuste degenerado (pocos equipos, marcadores sin varianza) puede
            # producir una matriz de goles invalida. Se omite la prediccion en
            # vez de tumbar el pipeline o el request del API.
            return results
        for index, grid in zip(predictable, grids, strict=True):
            results[index] = _normalized_outcome(grid.home_draw_away)
        return results


def _normalized_outcome(values: Sequence[float]) -> tuple[float, float, float] | None:
    home, draw, away = (float(value) for value in values)
    total = home + draw + away
    if total <= 0.0 or any(value < 0.0 for value in (home, draw, away)):
        return None
    return (home / total, draw / total, away / total)


def goal_samples_from_matches(matches: Sequence[Any]) -> list[GoalSample]:
    """Convierte `MatchResult` (u otro objeto con esos campos) en muestras."""
    samples: list[GoalSample] = []
    for match in matches:
        if match.home_goals is None or match.away_goals is None:
            continue
        samples.append(
            GoalSample(
                home_team=match.home_team,
                away_team=match.away_team,
                home_goals=int(match.home_goals),
                away_goals=int(match.away_goals),
                kickoff_utc=match.kickoff_utc,
            )
        )
    return samples

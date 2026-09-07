from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, cast

from sqlalchemy import CursorResult, func, select, update
from sqlalchemy.orm import Session

from futpredict.db.models import League, ModelMetric, ModelVersion


@dataclass(frozen=True)
class LeagueChampion:
    league_code: str
    model: str
    algorithm: str
    feature_set_version: str
    weighted_rps: float | None
    matches: int
    windows: int


@dataclass(frozen=True)
class ChampionPromotionSummary:
    champions: list[LeagueChampion] = field(default_factory=list)
    promoted_versions: int = 0
    demoted_versions: int = 0

    @property
    def champion_versions(self) -> int:
        return len(self.champions)


def promote_champion_by_rps(
    session: Session,
    *,
    min_matches: int = 100,
    commit: bool = True,
) -> ChampionPromotionSummary:
    """Marca un campeon POR LIGA: el modelo con menor RPS ponderado en esa liga.

    Antes se elegia un unico campeon global (el mejor promediando todas las
    ligas), lo que dejaba a Peru sin campeon porque su mejor modelo (elo_simple)
    no era el ganador global (market_avg_odds, que Peru ni tiene). Ahora cada
    liga promueve a su propio mejor modelo. La base impone un unico campeon por
    liga (indice parcial ``uq_one_champion_per_league``), asi que se marca una
    ``model_version`` por liga: la de la ventana de entrenamiento mas reciente.
    Primero se desmarcan todos los campeones vigentes para no violar el indice.
    """
    demoted = _clear_champions(session)
    best_rows = _best_model_per_league(session, min_matches=min_matches)

    champions: list[LeagueChampion] = []
    champion_ids: list[int] = []
    for row in best_rows:
        version_id = _latest_version_id(
            session,
            league_id=_required_int(row["league_id"]),
            name=str(row["model"]),
            algorithm=str(row["algorithm"]),
            feature_set_version=str(row["feature_set_version"]),
        )
        if version_id is None:
            continue
        champion_ids.append(version_id)
        champions.append(
            LeagueChampion(
                league_code=str(row["league_code"]),
                model=str(row["model"]),
                algorithm=str(row["algorithm"]),
                feature_set_version=str(row["feature_set_version"]),
                weighted_rps=_optional_float(row.get("weighted_rps")),
                matches=_required_int(row.get("matches")),
                windows=_required_int(row.get("windows")),
            )
        )

    promoted = 0
    if champion_ids:
        promoted = cast(
            "CursorResult[Any]",
            session.execute(
                update(ModelVersion)
                .where(ModelVersion.id.in_(champion_ids))
                .values(is_champion=True)
            ),
        ).rowcount

    if commit:
        session.commit()

    return ChampionPromotionSummary(
        champions=champions,
        promoted_versions=int(promoted),
        demoted_versions=demoted,
    )


def champion_status_rows(session: Session) -> list[dict[str, object]]:
    """Devuelve las model_versions marcadas como campeon, agrupadas por identidad."""
    rows = session.execute(
        select(
            ModelVersion.name.label("model"),
            ModelVersion.algorithm,
            ModelVersion.feature_set_version,
            func.count(ModelVersion.id).label("champion_versions"),
            func.count(func.distinct(ModelVersion.league_id)).label("leagues"),
            func.max(ModelVersion.train_window_end).label("last_train_window_end"),
        )
        .where(ModelVersion.is_champion.is_(True))
        .group_by(
            ModelVersion.name,
            ModelVersion.algorithm,
            ModelVersion.feature_set_version,
        )
        .order_by(ModelVersion.name)
    ).mappings()
    return [dict(row) for row in rows]


def _best_model_per_league(
    session: Session,
    *,
    min_matches: int,
) -> list[dict[str, object]]:
    """El mejor modelo (menor RPS ponderado) de cada liga con >= min_matches."""
    match_weight = func.sum(ModelMetric.n_matches)
    weighted_rps = func.sum(ModelMetric.rps * ModelMetric.n_matches) / match_weight
    aggregated = (
        select(
            ModelVersion.league_id.label("league_id"),
            League.code.label("league_code"),
            ModelVersion.name.label("model"),
            ModelVersion.algorithm.label("algorithm"),
            ModelVersion.feature_set_version.label("feature_set_version"),
            weighted_rps.label("weighted_rps"),
            match_weight.label("matches"),
            func.count(ModelMetric.id).label("windows"),
        )
        .join(ModelVersion, ModelVersion.id == ModelMetric.model_version_id)
        .join(League, League.id == ModelVersion.league_id)
        .group_by(
            ModelVersion.league_id,
            League.code,
            ModelVersion.name,
            ModelVersion.algorithm,
            ModelVersion.feature_set_version,
        )
        .having(match_weight >= min_matches)
        .subquery()
    )
    rank = (
        func.row_number()
        .over(partition_by=aggregated.c.league_id, order_by=aggregated.c.weighted_rps.asc())
        .label("rank")
    )
    ranked = select(aggregated, rank).subquery()
    statement = (
        select(ranked)
        .where(ranked.c.rank == 1)
        .order_by(ranked.c.league_code)
    )
    return [dict(row) for row in session.execute(statement).mappings()]


def _latest_version_id(
    session: Session,
    *,
    league_id: int,
    name: str,
    algorithm: str,
    feature_set_version: str,
) -> int | None:
    statement = (
        select(ModelVersion.id)
        .where(
            ModelVersion.league_id == league_id,
            ModelVersion.name == name,
            ModelVersion.algorithm == algorithm,
            ModelVersion.feature_set_version == feature_set_version,
        )
        .order_by(ModelVersion.train_window_end.desc(), ModelVersion.id.desc())
        .limit(1)
    )
    value = session.execute(statement).scalars().first()
    return None if value is None else int(value)


def _clear_champions(session: Session) -> int:
    return cast(
        "CursorResult[Any]",
        session.execute(
            update(ModelVersion)
            .where(ModelVersion.is_champion.is_(True))
            .values(is_champion=False)
        ),
    ).rowcount


def _optional_float(value: object) -> float | None:
    if value is None:
        return None
    if isinstance(value, int | float | Decimal):
        return float(value)
    return float(str(value))


def _required_int(value: object) -> int:
    if value is None:
        return 0
    if isinstance(value, int):
        return value
    if isinstance(value, float | Decimal | str):
        return int(value)
    return int(str(value))

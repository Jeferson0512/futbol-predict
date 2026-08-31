from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, cast

from sqlalchemy import CursorResult, func, select, update
from sqlalchemy.orm import Session

from futpredict.db.models import ModelVersion
from futpredict.evaluation.db_models import champion_model_row


@dataclass(frozen=True)
class ChampionPromotionSummary:
    champion_model: str | None
    algorithm: str | None
    feature_set_version: str | None
    weighted_rps: float | None
    matches: int
    windows: int
    promoted_versions: int
    demoted_versions: int
    champion_versions: int


def promote_champion_by_rps(
    session: Session,
    *,
    min_matches: int = 100,
    commit: bool = True,
) -> ChampionPromotionSummary:
    """Marca como campeon al modelo con menor RPS ponderado y desmarca al resto.

    El campeon se elige globalmente por RPS ponderado (nombre, algoritmo,
    feature_set_version). Como la base impone un unico campeon por liga
    (indice parcial ``uq_one_champion_per_league``), se marca exactamente una
    ``model_version`` por liga: la de la ventana de entrenamiento mas reciente
    de ese modelo. Primero se desmarcan todos los campeones vigentes para no
    violar el indice durante la transicion.
    """
    demoted = _clear_champions(session)
    row = champion_model_row(session, min_matches=min_matches)
    if row is None:
        if commit:
            session.commit()
        return ChampionPromotionSummary(
            champion_model=None,
            algorithm=None,
            feature_set_version=None,
            weighted_rps=None,
            matches=0,
            windows=0,
            promoted_versions=0,
            demoted_versions=demoted,
            champion_versions=0,
        )

    name = str(row["model"])
    algorithm = str(row["algorithm"])
    feature_set_version = str(row["feature_set_version"])
    champion_ids = _latest_version_ids_per_league(
        session,
        name=name,
        algorithm=algorithm,
        feature_set_version=feature_set_version,
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
        champion_model=name,
        algorithm=algorithm,
        feature_set_version=feature_set_version,
        weighted_rps=_optional_float(row.get("weighted_rps")),
        matches=_required_int(row.get("matches")),
        windows=_required_int(row.get("windows")),
        promoted_versions=int(promoted),
        demoted_versions=demoted,
        champion_versions=len(champion_ids),
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


def _clear_champions(session: Session) -> int:
    return cast(
        "CursorResult[Any]",
        session.execute(
            update(ModelVersion)
            .where(ModelVersion.is_champion.is_(True))
            .values(is_champion=False)
        ),
    ).rowcount


def _latest_version_ids_per_league(
    session: Session,
    *,
    name: str,
    algorithm: str,
    feature_set_version: str,
) -> list[int]:
    statement = (
        select(ModelVersion.id)
        .where(
            ModelVersion.name == name,
            ModelVersion.algorithm == algorithm,
            ModelVersion.feature_set_version == feature_set_version,
        )
        .distinct(ModelVersion.league_id)
        .order_by(
            ModelVersion.league_id,
            ModelVersion.train_window_end.desc(),
            ModelVersion.id.desc(),
        )
    )
    return [int(value) for value in session.execute(statement).scalars().all()]


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

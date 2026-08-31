from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import cast

from sqlalchemy import Table, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from futpredict.data.db_matches import league_codes_from_divisions
from futpredict.db.models import League, ModelMetric, ModelVersion
from futpredict.evaluation.walk_forward import WalkForwardMetric

WALK_FORWARD_FEATURE_SET_VERSION = "baseline_walk_forward_v1"
ALGORITHM_BY_MODEL: dict[str, str] = {
    "always_home": "constant_baseline",
    "club_elo": "external_elo",
    "historical_frequency": "historical_frequency",
    "elo_simple": "elo",
    "market_avg_odds": "market_odds",
    "logistic_regression": "multinomial_logit",
    "gradient_boosting": "gradient_boosting",
    "logistic_calibrated": "logistic_isotonic",
}


@dataclass(frozen=True)
class WalkForwardPersistenceSummary:
    model_versions: int
    metrics: int


def upsert_walk_forward_metrics(
    session: Session,
    metrics: Sequence[WalkForwardMetric],
    *,
    evaluated_at: datetime | None = None,
    commit: bool = True,
) -> WalkForwardPersistenceSummary:
    timestamp = evaluated_at if evaluated_at is not None else datetime.now(UTC)
    league_ids = _league_ids_by_division(session, sorted({metric.division for metric in metrics}))
    model_version_keys: set[tuple[str, str, str, str, datetime, datetime]] = set()

    for metric in metrics:
        model_version_id = _upsert_model_version(session, metric, league_ids, timestamp)
        _upsert_model_metric(session, metric, model_version_id, timestamp)
        model_version_keys.add(
            (
                metric.division,
                metric.summary.model,
                _algorithm_for_model(metric.summary.model),
                WALK_FORWARD_FEATURE_SET_VERSION,
                metric.train_window_start_utc,
                metric.train_window_end_utc,
            )
        )

    if commit:
        session.commit()

    return WalkForwardPersistenceSummary(
        model_versions=len(model_version_keys),
        metrics=len(metrics),
    )


def _upsert_model_version(
    session: Session,
    metric: WalkForwardMetric,
    league_ids: dict[str, int],
    timestamp: datetime,
) -> int:
    table = cast(Table, ModelVersion.__table__)
    base = insert(table).values(
        league_id=league_ids[metric.division],
        name=metric.summary.model,
        algorithm=_algorithm_for_model(metric.summary.model),
        hyperparams={
            "evaluation_mode": "expanding_walk_forward",
            "evaluation_season": metric.evaluation_season,
            "train_start_season": metric.train_start_season,
            "train_end_season": metric.train_end_season,
        },
        trained_at=timestamp,
        train_window_start=metric.train_window_start_utc,
        train_window_end=metric.train_window_end_utc,
        feature_set_version=WALK_FORWARD_FEATURE_SET_VERSION,
        artifact_uri=None,
        is_champion=False,
    )
    statement = base.on_conflict_do_update(
        constraint="uq_model_version_identity",
        set_={
            "hyperparams": base.excluded.hyperparams,
            "trained_at": base.excluded.trained_at,
            "artifact_uri": func.coalesce(base.excluded.artifact_uri, table.c.artifact_uri),
        },
    ).returning(table.c.id)
    return _scalar_int(session.execute(statement).scalar_one())


def _upsert_model_metric(
    session: Session,
    metric: WalkForwardMetric,
    model_version_id: int,
    timestamp: datetime,
) -> None:
    table = cast(Table, ModelMetric.__table__)
    base = insert(table).values(
        model_version_id=model_version_id,
        evaluated_at=timestamp,
        window_label=metric.window_label,
        n_matches=metric.summary.n_matches,
        rps=_metric_decimal(metric.summary.rps),
        log_loss=_metric_decimal(metric.summary.log_loss),
        brier=_metric_decimal(metric.summary.brier),
        accuracy=_metric_decimal(metric.summary.accuracy),
        calibration_error=None,
    )
    statement = base.on_conflict_do_update(
        constraint="uq_model_metric_version_window",
        set_={
            "evaluated_at": base.excluded.evaluated_at,
            "n_matches": base.excluded.n_matches,
            "rps": base.excluded.rps,
            "log_loss": base.excluded.log_loss,
            "brier": base.excluded.brier,
            "accuracy": base.excluded.accuracy,
            "calibration_error": base.excluded.calibration_error,
        },
    )
    session.execute(statement)


def _league_ids_by_division(session: Session, divisions: list[str]) -> dict[str, int]:
    if not divisions:
        return {}
    league_codes_by_division = {
        division: league_codes_from_divisions([division])[0] for division in divisions
    }
    statement = select(League.id, League.code).where(
        League.code.in_(list(league_codes_by_division.values()))
    )
    ids_by_code = {cast(str, row[1]): cast(int, row[0]) for row in session.execute(statement)}
    missing = sorted(set(league_codes_by_division.values()) - set(ids_by_code))
    if missing:
        msg = f"missing leagues in database: {', '.join(missing)}"
        raise ValueError(msg)
    return {
        division: ids_by_code[league_code]
        for division, league_code in league_codes_by_division.items()
    }


def _algorithm_for_model(model: str) -> str:
    try:
        return ALGORITHM_BY_MODEL[model]
    except KeyError as exc:
        msg = f"unsupported baseline model for persistence: {model}"
        raise ValueError(msg) from exc


def _metric_decimal(value: float) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.00000001"))


def _scalar_int(value: object) -> int:
    if not isinstance(value, int):
        msg = f"expected integer primary key, got {type(value).__name__}"
        raise TypeError(msg)
    return value

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import cast

from sqlalchemy import Table, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from futpredict.db.models import Match, ModelVersion, Prediction
from futpredict.domain.matches import result_from_goals
from futpredict.evaluation.db_walk_forward import (
    WALK_FORWARD_FEATURE_SET_VERSION,
    _algorithm_for_model,
    _league_ids_by_division,
)
from futpredict.evaluation.metrics import brier_score
from futpredict.evaluation.metrics import log_loss as log_loss_metric
from futpredict.evaluation.rps import ranked_probability_score
from futpredict.evaluation.walk_forward_predictions import WalkForwardPrediction


@dataclass(frozen=True)
class PredictionPersistenceSummary:
    model_versions: int
    candidates: int
    inserted_predictions: int
    existing_predictions: int


@dataclass(frozen=True)
class PredictionEvaluationSummary:
    evaluated_predictions: int


def freeze_walk_forward_predictions(
    session: Session,
    predictions: Sequence[WalkForwardPrediction],
    *,
    frozen_at: datetime | None = None,
    commit: bool = True,
) -> PredictionPersistenceSummary:
    timestamp = frozen_at if frozen_at is not None else datetime.now(UTC)
    league_ids = _league_ids_by_division(
        session,
        sorted({prediction.division for prediction in predictions}),
    )
    model_version_ids: dict[tuple[str, str, datetime, datetime], int] = {}
    prediction_rows: list[dict[str, object]] = []

    for prediction in predictions:
        model_version_key = (
            prediction.division,
            prediction.prediction.model,
            prediction.train_window_start_utc,
            prediction.train_window_end_utc,
        )
        model_version_id = model_version_ids.get(model_version_key)
        if model_version_id is None:
            model_version_id = _upsert_prediction_model_version(
                session,
                prediction,
                league_ids[prediction.division],
                timestamp,
            )
            model_version_ids[model_version_key] = model_version_id
        prediction_rows.append(_prediction_values(prediction, model_version_id))

    inserted_predictions = _insert_immutable_prediction_rows(session, prediction_rows)
    existing_predictions = len(prediction_rows) - inserted_predictions

    if commit:
        session.commit()

    return PredictionPersistenceSummary(
        model_versions=len(model_version_ids),
        candidates=len(predictions),
        inserted_predictions=inserted_predictions,
        existing_predictions=existing_predictions,
    )


def evaluate_pending_predictions(
    session: Session,
    *,
    evaluated_at: datetime | None = None,
    commit: bool = True,
) -> PredictionEvaluationSummary:
    _timestamp = evaluated_at if evaluated_at is not None else datetime.now(UTC)
    statement = (
        select(Prediction, Match.home_goals, Match.away_goals)
        .join(Match, Prediction.match_id == Match.id)
        .where(
            Match.status == "finished",
            Match.home_goals.is_not(None),
            Match.away_goals.is_not(None),
            Prediction.rps.is_(None),
        )
        .order_by(Prediction.id)
    )

    evaluated = 0
    for row in session.execute(statement):
        prediction = cast(Prediction, row[0])
        home_goals = _required_score(cast(int | None, row[1]), "home_goals")
        away_goals = _required_score(cast(int | None, row[2]), "away_goals")
        outcome = result_from_goals(home_goals, away_goals)
        probabilities = (
            float(prediction.prob_home),
            float(prediction.prob_draw),
            float(prediction.prob_away),
        )
        prediction.actual_outcome = outcome
        prediction.rps = _metric_decimal(ranked_probability_score(probabilities, outcome))
        prediction.log_loss = _metric_decimal(log_loss_metric(probabilities, outcome))
        prediction.brier = _metric_decimal(brier_score(probabilities, outcome))
        evaluated += 1

    if commit:
        session.commit()

    return PredictionEvaluationSummary(evaluated_predictions=evaluated)


def prediction_status_rows(session: Session) -> list[dict[str, object]]:
    rows = session.execute(
        select(
            ModelVersion.name.label("model"),
            ModelVersion.algorithm,
            ModelVersion.feature_set_version,
            func.count(Prediction.id).label("predictions"),
            func.count(Prediction.rps).label("evaluated"),
            func.avg(Prediction.rps).label("avg_rps"),
            func.avg(Prediction.log_loss).label("avg_log_loss"),
            func.avg(Prediction.brier).label("avg_brier"),
        )
        .join(ModelVersion, ModelVersion.id == Prediction.model_version_id)
        .group_by(
            ModelVersion.name,
            ModelVersion.algorithm,
            ModelVersion.feature_set_version,
        )
        .order_by(func.avg(Prediction.rps))
    ).mappings()
    return [dict(row) for row in rows]


def _upsert_prediction_model_version(
    session: Session,
    prediction: WalkForwardPrediction,
    league_id: int,
    timestamp: datetime,
) -> int:
    table = cast(Table, ModelVersion.__table__)
    model_name = prediction.prediction.model
    base = insert(table).values(
        league_id=league_id,
        name=model_name,
        algorithm=_algorithm_for_model(model_name),
        hyperparams={
            "evaluation_mode": "expanding_walk_forward_predictions",
            "evaluation_season": prediction.evaluation_season,
            "train_start_season": prediction.train_start_season,
            "train_end_season": prediction.train_end_season,
        },
        trained_at=timestamp,
        train_window_start=prediction.train_window_start_utc,
        train_window_end=prediction.train_window_end_utc,
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


def _prediction_values(
    prediction: WalkForwardPrediction,
    model_version_id: int,
) -> dict[str, object]:
    match = prediction.prediction.match
    if match.match_id is None:
        msg = "cannot freeze prediction without match_id"
        raise ValueError(msg)
    if prediction.train_window_end_utc >= match.kickoff_utc:
        msg = "prediction timestamp must be before kickoff"
        raise ValueError(msg)

    prob_home, prob_draw, prob_away = prediction.prediction.probabilities
    return {
        "match_id": match.match_id,
        "model_version_id": model_version_id,
        "kickoff_utc": match.kickoff_utc,
        "predicted_at": prediction.train_window_end_utc,
        "prob_home": _probability_decimal(prob_home),
        "prob_draw": _probability_decimal(prob_draw),
        "prob_away": _probability_decimal(prob_away),
        "expected_home_goals": None,
        "expected_away_goals": None,
        "actual_outcome": None,
        "rps": None,
        "log_loss": None,
        "brier": None,
    }


def _insert_immutable_prediction_rows(
    session: Session,
    rows: Sequence[dict[str, object]],
    *,
    chunk_size: int = 1000,
) -> int:
    if not rows:
        return 0

    table = cast(Table, Prediction.__table__)
    inserted = 0
    for index in range(0, len(rows), chunk_size):
        chunk = rows[index : index + chunk_size]
        statement = (
            insert(table)
            .values(chunk)
            .on_conflict_do_nothing(constraint="uq_prediction_match_model")
            .returning(table.c.id)
        )
        inserted += len(session.execute(statement).scalars().all())
    return inserted


def _probability_decimal(value: float) -> Decimal:
    if value < 0 or value > 1:
        msg = f"probability must be between 0 and 1, got {value}"
        raise ValueError(msg)
    return Decimal(str(value)).quantize(Decimal("0.00000001"))


def _metric_decimal(value: float) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.00000001"))


def _required_score(value: int | None, field_name: str) -> int:
    if value is None:
        msg = f"finished match is missing {field_name}"
        raise ValueError(msg)
    return value


def _scalar_int(value: object) -> int:
    if not isinstance(value, int):
        msg = f"expected integer primary key, got {type(value).__name__}"
        raise TypeError(msg)
    return value

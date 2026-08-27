from __future__ import annotations

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from futpredict.db.models import ModelMetric, ModelVersion


def model_ranking_rows(session: Session, *, min_matches: int = 1) -> list[dict[str, object]]:
    match_weight = func.sum(ModelMetric.n_matches)
    calibration_weight = func.sum(
        case((ModelMetric.calibration_error.is_not(None), ModelMetric.n_matches), else_=0)
    )
    weighted_rps = func.sum(ModelMetric.rps * ModelMetric.n_matches) / match_weight
    weighted_log_loss = func.sum(ModelMetric.log_loss * ModelMetric.n_matches) / match_weight
    weighted_brier = func.sum(ModelMetric.brier * ModelMetric.n_matches) / match_weight
    weighted_accuracy = func.sum(ModelMetric.accuracy * ModelMetric.n_matches) / match_weight
    weighted_calibration_error = (
        func.sum(ModelMetric.calibration_error * ModelMetric.n_matches)
        / func.nullif(calibration_weight, 0)
    )
    rows = session.execute(
        select(
            ModelVersion.name.label("model"),
            ModelVersion.algorithm,
            ModelVersion.feature_set_version,
            func.count(ModelMetric.id).label("windows"),
            match_weight.label("matches"),
            weighted_rps.label("weighted_rps"),
            weighted_log_loss.label("weighted_log_loss"),
            weighted_brier.label("weighted_brier"),
            weighted_accuracy.label("weighted_accuracy"),
            weighted_calibration_error.label("weighted_calibration_error"),
        )
        .join(ModelVersion, ModelVersion.id == ModelMetric.model_version_id)
        .group_by(
            ModelVersion.name,
            ModelVersion.algorithm,
            ModelVersion.feature_set_version,
        )
        .having(match_weight >= min_matches)
        .order_by(weighted_rps)
    ).mappings()
    return [dict(row) for row in rows]


def champion_model_row(session: Session, *, min_matches: int = 1) -> dict[str, object] | None:
    rows = model_ranking_rows(session, min_matches=min_matches)
    return rows[0] if rows else None

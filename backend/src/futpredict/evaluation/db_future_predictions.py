from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import cast

from sqlalchemy import Table, func
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from futpredict.data.db_fixtures import load_upcoming_fixtures_from_db
from futpredict.data.db_matches import load_finished_match_results_before_from_db
from futpredict.db.models import ModelVersion
from futpredict.evaluation.db_predictions import (
    _insert_immutable_prediction_rows,
    _probability_decimal,
    _scalar_int,
)
from futpredict.evaluation.db_walk_forward import _league_ids_by_division
from futpredict.evaluation.future_predictions import (
    FixturePrediction,
    build_fixture_predictions,
)


@dataclass(frozen=True)
class FuturePredictionFreezeSummary:
    frozen_at: datetime
    fixtures: int
    eligible_fixtures: int
    model_versions: int
    candidates: int
    inserted_predictions: int
    existing_predictions: int
    skipped_without_window: int


def freeze_future_predictions(
    session: Session,
    *,
    frozen_at: datetime | None = None,
    days: int = 14,
    division_codes: list[str] | None = None,
    limit: int = 200,
    model_names: list[str] | None = None,
    commit: bool = True,
) -> FuturePredictionFreezeSummary:
    """Congela predicciones inmutables para los fixtures de la proxima jornada.

    Cada prediccion se registra con ``predicted_at`` igual a ``frozen_at`` (ahora),
    siempre estrictamente antes del ``kickoff_utc``, respetando el registro
    inmutable: si ya existe una prediccion para ese partido y modelo, no se
    sobrescribe.
    """
    timestamp = frozen_at if frozen_at is not None else datetime.now(UTC)

    fixtures = load_upcoming_fixtures_from_db(
        session,
        start_at=timestamp,
        end_at=timestamp + timedelta(days=days),
        division_codes=division_codes,
        limit=limit,
    )
    eligible = [
        fixture
        for fixture in fixtures
        if fixture.match_id is not None and fixture.kickoff_utc > timestamp
    ]
    if not eligible:
        return FuturePredictionFreezeSummary(
            frozen_at=timestamp,
            fixtures=len(fixtures),
            eligible_fixtures=0,
            model_versions=0,
            candidates=0,
            inserted_predictions=0,
            existing_predictions=0,
            skipped_without_window=0,
        )

    training_matches = load_finished_match_results_before_from_db(
        session,
        cutoff_utc=timestamp,
        division_codes=division_codes,
    )
    predictions = build_fixture_predictions(
        eligible,
        training_matches,
        model_names=model_names,
    )

    league_ids = _league_ids_by_division(
        session,
        sorted({prediction.fixture.division for prediction in predictions}),
    )

    model_version_ids: dict[tuple[str, str, str, str, datetime, datetime], int] = {}
    prediction_rows: list[dict[str, object]] = []
    skipped_without_window = 0

    for prediction in predictions:
        if (
            prediction.train_window_start_utc is None
            or prediction.train_window_end_utc is None
        ):
            skipped_without_window += 1
            continue

        key = (
            prediction.fixture.division,
            prediction.model,
            prediction.algorithm,
            prediction.feature_set_version,
            prediction.train_window_start_utc,
            prediction.train_window_end_utc,
        )
        model_version_id = model_version_ids.get(key)
        if model_version_id is None:
            model_version_id = _upsert_future_model_version(
                session,
                prediction,
                league_ids[prediction.fixture.division],
                timestamp,
            )
            model_version_ids[key] = model_version_id
        prediction_rows.append(
            _future_prediction_values(prediction, model_version_id, timestamp)
        )

    inserted = _insert_immutable_prediction_rows(session, prediction_rows)
    existing = len(prediction_rows) - inserted

    if commit:
        session.commit()

    return FuturePredictionFreezeSummary(
        frozen_at=timestamp,
        fixtures=len(fixtures),
        eligible_fixtures=len(eligible),
        model_versions=len(model_version_ids),
        candidates=len(prediction_rows),
        inserted_predictions=inserted,
        existing_predictions=existing,
        skipped_without_window=skipped_without_window,
    )


def _upsert_future_model_version(
    session: Session,
    prediction: FixturePrediction,
    league_id: int,
    timestamp: datetime,
) -> int:
    table = cast(Table, ModelVersion.__table__)
    base = insert(table).values(
        league_id=league_id,
        name=prediction.model,
        algorithm=prediction.algorithm,
        hyperparams={
            "evaluation_mode": "future_fixture_freeze",
            "season": prediction.fixture.season,
            "frozen_at": timestamp.isoformat(),
        },
        trained_at=timestamp,
        train_window_start=prediction.train_window_start_utc,
        train_window_end=prediction.train_window_end_utc,
        feature_set_version=prediction.feature_set_version,
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


def _future_prediction_values(
    prediction: FixturePrediction,
    model_version_id: int,
    timestamp: datetime,
) -> dict[str, object]:
    fixture = prediction.fixture
    if fixture.match_id is None:
        msg = "cannot freeze future prediction without match_id"
        raise ValueError(msg)
    if timestamp >= fixture.kickoff_utc:
        msg = "future prediction timestamp must be before kickoff"
        raise ValueError(msg)

    prob_home, prob_draw, prob_away = prediction.probabilities
    return {
        "match_id": fixture.match_id,
        "model_version_id": model_version_id,
        "kickoff_utc": fixture.kickoff_utc,
        "predicted_at": timestamp,
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

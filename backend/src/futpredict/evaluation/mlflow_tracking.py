from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from types import TracebackType
from typing import Any, cast

import httpx
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from futpredict.db.models import League, ModelMetric, ModelVersion

DEFAULT_MLFLOW_EXPERIMENT_NAME = "Futbol Predict Baselines"
FUTPREDICT_SOURCE_TAG = "futpredict_model_metrics"


@dataclass(frozen=True)
class MlflowRunInfo:
    run_id: str
    artifact_uri: str


@dataclass(frozen=True)
class MlflowSyncSummary:
    experiment_id: str
    scanned_model_versions: int
    skipped_model_versions: int
    reused_runs: int
    created_runs: int
    logged_runs: int
    updated_model_versions: int


@dataclass(frozen=True)
class _ModelMetricRun:
    model_version_id: int
    model_metric_id: int
    league_code: str
    league_name: str
    model: str
    algorithm: str
    feature_set_version: str
    hyperparams: Mapping[str, Any]
    trained_at: datetime
    train_window_start: datetime
    train_window_end: datetime
    artifact_uri: str | None
    window_label: str
    evaluated_at: datetime
    n_matches: int
    rps: Decimal
    log_loss: Decimal | None
    brier: Decimal | None
    accuracy: Decimal | None
    calibration_error: Decimal | None


class MlflowRestClient:
    def __init__(
        self,
        tracking_uri: str,
        *,
        timeout: float = 30.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._tracking_uri = tracking_uri.rstrip("/")
        self._http = httpx.Client(timeout=timeout, transport=transport)

    def __enter__(self) -> MlflowRestClient:
        return self

    def __exit__(
        self,
        _exc_type: type[BaseException] | None,
        _exc: BaseException | None,
        _traceback: TracebackType | None,
    ) -> None:
        self.close()

    def close(self) -> None:
        self._http.close()

    def get_or_create_experiment_id(self, experiment_name: str) -> str:
        experiment_id = self.get_experiment_id(experiment_name)
        if experiment_id is not None:
            return experiment_id

        response = self._http.post(
            self._url("experiments/create"),
            json={"name": experiment_name},
        )
        if _is_mlflow_error(response, "RESOURCE_ALREADY_EXISTS"):
            experiment_id = self.get_experiment_id(experiment_name)
            if experiment_id is not None:
                return experiment_id
        data = _response_json(response)
        return _required_str(data, "experiment_id")

    def get_experiment_id(self, experiment_name: str) -> str | None:
        response = self._http.get(
            self._url("experiments/get-by-name"),
            params={"experiment_name": experiment_name},
        )
        if _is_mlflow_error(response, "RESOURCE_DOES_NOT_EXIST"):
            return None
        data = _response_json(response)
        experiment = _required_mapping(data, "experiment")
        return _required_str(experiment, "experiment_id")

    def find_run_for_model_version(
        self,
        *,
        experiment_id: str,
        model_version_id: int,
    ) -> MlflowRunInfo | None:
        response = self._http.post(
            self._url("runs/search"),
            json={
                "experiment_ids": [experiment_id],
                "filter": f"tags.futpredict_model_version_id = '{model_version_id}'",
                "max_results": 1,
            },
        )
        data = _response_json(response)
        runs = data.get("runs")
        if not isinstance(runs, list) or not runs:
            return None
        first_run = runs[0]
        if not isinstance(first_run, dict):
            msg = "MLflow search returned an invalid run payload."
            raise ValueError(msg)
        return _run_info(cast(Mapping[str, Any], first_run))

    def create_run(
        self,
        *,
        experiment_id: str,
        row: _ModelMetricRun,
    ) -> MlflowRunInfo:
        response = self._http.post(
            self._url("runs/create"),
            json={
                "experiment_id": experiment_id,
                "run_name": _run_name(row),
                "start_time": _timestamp_ms(row.trained_at),
                "tags": _tag_payload(row),
            },
        )
        data = _response_json(response)
        return _run_info(_required_mapping(data, "run"))

    def log_batch(
        self,
        *,
        run_id: str,
        row: _ModelMetricRun,
        include_params: bool = True,
    ) -> None:
        timestamp_ms = _timestamp_ms(row.evaluated_at)
        payload: dict[str, object] = {
            "run_id": run_id,
            "metrics": _metric_payload(row, timestamp_ms),
            "tags": _tag_payload(row),
        }
        if include_params:
            payload["params"] = _param_payload(row)
        response = self._http.post(
            self._url("runs/log-batch"),
            json=payload,
        )
        _response_json(response)

    def finish_run(self, *, run_id: str, finished_at: datetime) -> None:
        response = self._http.post(
            self._url("runs/update"),
            json={
                "run_id": run_id,
                "status": "FINISHED",
                "end_time": _timestamp_ms(finished_at),
            },
        )
        _response_json(response)

    def _url(self, endpoint: str) -> str:
        return f"{self._tracking_uri}/api/2.0/mlflow/{endpoint.lstrip('/')}"


def sync_model_versions_to_mlflow(
    session: Session,
    *,
    tracking_uri: str,
    experiment_name: str = DEFAULT_MLFLOW_EXPERIMENT_NAME,
    only_missing: bool = True,
    timeout: float = 30.0,
    commit: bool = True,
    client: MlflowRestClient | None = None,
) -> MlflowSyncSummary:
    rows = _model_metric_runs(session)
    owns_client = client is None
    mlflow = client or MlflowRestClient(tracking_uri, timeout=timeout)

    skipped = 0
    reused = 0
    created = 0
    logged = 0
    updated = 0

    try:
        experiment_id = mlflow.get_or_create_experiment_id(experiment_name)
        for row in rows:
            if only_missing and row.artifact_uri:
                skipped += 1
                continue

            existing_run = mlflow.find_run_for_model_version(
                experiment_id=experiment_id,
                model_version_id=row.model_version_id,
            )
            if existing_run is not None:
                if not only_missing:
                    mlflow.log_batch(
                        run_id=existing_run.run_id,
                        row=row,
                        include_params=False,
                    )
                    logged += 1
                _set_model_version_artifact_uri(session, row.model_version_id, existing_run)
                reused += 1
                updated += 1
                continue

            run_info = mlflow.create_run(experiment_id=experiment_id, row=row)
            mlflow.log_batch(run_id=run_info.run_id, row=row)
            mlflow.finish_run(run_id=run_info.run_id, finished_at=datetime.now(UTC))
            _set_model_version_artifact_uri(session, row.model_version_id, run_info)
            created += 1
            logged += 1
            updated += 1

        if commit:
            session.commit()
    finally:
        if owns_client:
            mlflow.close()

    return MlflowSyncSummary(
        experiment_id=experiment_id,
        scanned_model_versions=len(rows),
        skipped_model_versions=skipped,
        reused_runs=reused,
        created_runs=created,
        logged_runs=logged,
        updated_model_versions=updated,
    )


def _model_metric_runs(session: Session) -> list[_ModelMetricRun]:
    statement = (
        select(
            ModelVersion.id.label("model_version_id"),
            ModelMetric.id.label("model_metric_id"),
            League.code.label("league_code"),
            League.name.label("league_name"),
            ModelVersion.name.label("model"),
            ModelVersion.algorithm,
            ModelVersion.feature_set_version,
            ModelVersion.hyperparams,
            ModelVersion.trained_at,
            ModelVersion.train_window_start,
            ModelVersion.train_window_end,
            ModelVersion.artifact_uri,
            ModelMetric.window_label,
            ModelMetric.evaluated_at,
            ModelMetric.n_matches,
            ModelMetric.rps,
            ModelMetric.log_loss,
            ModelMetric.brier,
            ModelMetric.accuracy,
            ModelMetric.calibration_error,
        )
        .join(League, League.id == ModelVersion.league_id)
        .join(ModelMetric, ModelMetric.model_version_id == ModelVersion.id)
        .order_by(League.code, ModelVersion.name, ModelVersion.train_window_end)
    )

    rows: list[_ModelMetricRun] = []
    for raw_row in session.execute(statement).mappings():
        row = cast(Mapping[str, Any], raw_row)
        rows.append(
            _ModelMetricRun(
                model_version_id=_required_int(row, "model_version_id"),
                model_metric_id=_required_int(row, "model_metric_id"),
                league_code=_required_str(row, "league_code"),
                league_name=_required_str(row, "league_name"),
                model=_required_str(row, "model"),
                algorithm=_required_str(row, "algorithm"),
                feature_set_version=_required_str(row, "feature_set_version"),
                hyperparams=_optional_mapping(row, "hyperparams"),
                trained_at=_required_datetime(row, "trained_at"),
                train_window_start=_required_datetime(row, "train_window_start"),
                train_window_end=_required_datetime(row, "train_window_end"),
                artifact_uri=_optional_str(row, "artifact_uri"),
                window_label=_required_str(row, "window_label"),
                evaluated_at=_required_datetime(row, "evaluated_at"),
                n_matches=_required_int(row, "n_matches"),
                rps=_required_decimal(row, "rps"),
                log_loss=_optional_decimal(row, "log_loss"),
                brier=_optional_decimal(row, "brier"),
                accuracy=_optional_decimal(row, "accuracy"),
                calibration_error=_optional_decimal(row, "calibration_error"),
            )
        )
    return rows


def _set_model_version_artifact_uri(
    session: Session,
    model_version_id: int,
    run_info: MlflowRunInfo,
) -> None:
    session.execute(
        update(ModelVersion)
        .where(ModelVersion.id == model_version_id)
        .values(artifact_uri=run_info.artifact_uri)
    )


def _run_name(row: _ModelMetricRun) -> str:
    train_start = _season_param(row.hyperparams, "train_start_season")
    train_end = _season_param(row.hyperparams, "train_end_season")
    evaluation = _season_param(row.hyperparams, "evaluation_season")
    return f"{row.league_code}/{row.model}/{train_start}-{train_end}/eval-{evaluation}"


def _metric_payload(row: _ModelMetricRun, timestamp_ms: int) -> list[dict[str, object]]:
    metrics = {
        "n_matches": float(row.n_matches),
        "rps": float(row.rps),
        "log_loss": _optional_float(row.log_loss),
        "brier": _optional_float(row.brier),
        "accuracy": _optional_float(row.accuracy),
        "calibration_error": _optional_float(row.calibration_error),
    }
    return [
        {"key": key, "value": value, "timestamp": timestamp_ms, "step": 0}
        for key, value in metrics.items()
        if value is not None
    ]


def _param_payload(row: _ModelMetricRun) -> list[dict[str, str]]:
    params = {
        "league_code": row.league_code,
        "league_name": row.league_name,
        "model": row.model,
        "algorithm": row.algorithm,
        "feature_set_version": row.feature_set_version,
        "window_label": row.window_label,
        "train_window_start": row.train_window_start.isoformat(),
        "train_window_end": row.train_window_end.isoformat(),
    }
    for key, value in sorted(row.hyperparams.items()):
        params[f"hyperparam_{key}"] = _param_value(value)
    return [{"key": key, "value": _truncate(value)} for key, value in params.items()]


def _tag_payload(row: _ModelMetricRun) -> list[dict[str, str]]:
    return [
        {"key": "futpredict_source", "value": FUTPREDICT_SOURCE_TAG},
        {"key": "futpredict_model_version_id", "value": str(row.model_version_id)},
        {"key": "futpredict_model_metric_id", "value": str(row.model_metric_id)},
        {"key": "futpredict_model", "value": row.model},
        {"key": "futpredict_league", "value": row.league_code},
    ]


def _run_info(run: Mapping[str, Any]) -> MlflowRunInfo:
    info = _required_mapping(run, "info")
    run_id = _required_str(info, "run_id")
    artifact_uri = _optional_str(info, "artifact_uri") or f"mlflow://runs/{run_id}"
    return MlflowRunInfo(run_id=run_id, artifact_uri=artifact_uri)


def _response_json(response: httpx.Response) -> Mapping[str, Any]:
    response.raise_for_status()
    data = response.json()
    if not isinstance(data, dict):
        msg = "MLflow returned a non-object JSON response."
        raise ValueError(msg)
    return cast(Mapping[str, Any], data)


def _is_mlflow_error(response: httpx.Response, error_code: str) -> bool:
    if response.status_code < 400:
        return False
    try:
        data = response.json()
    except ValueError:
        return False
    if not isinstance(data, dict):
        return False
    return data.get("error_code") == error_code


def _timestamp_ms(value: datetime) -> int:
    normalized = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    return int(normalized.timestamp() * 1000)


def _season_param(values: Mapping[str, Any], key: str) -> str:
    value = values.get(key)
    return str(value) if value is not None else "unknown"


def _param_value(value: object) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _optional_float(value: Decimal | None) -> float | None:
    if value is None:
        return None
    return float(value)


def _truncate(value: str, *, max_length: int = 240) -> str:
    if len(value) <= max_length:
        return value
    return value[: max_length - 3] + "..."


def _required_mapping(row: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    value = row.get(key)
    if not isinstance(value, dict):
        msg = f"expected MLflow field '{key}' to be an object"
        raise ValueError(msg)
    return cast(Mapping[str, Any], value)


def _optional_mapping(row: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    value = row.get(key)
    if value is None:
        return {}
    if not isinstance(value, dict):
        msg = f"expected field '{key}' to be an object"
        raise ValueError(msg)
    return cast(Mapping[str, Any], value)


def _required_int(row: Mapping[str, Any], key: str) -> int:
    value = row.get(key)
    if not isinstance(value, int):
        msg = f"expected field '{key}' to be an int"
        raise ValueError(msg)
    return value


def _required_str(row: Mapping[str, Any], key: str) -> str:
    value = row.get(key)
    if not isinstance(value, str) or not value:
        msg = f"expected field '{key}' to be a non-empty string"
        raise ValueError(msg)
    return value


def _optional_str(row: Mapping[str, Any], key: str) -> str | None:
    value = row.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        msg = f"expected field '{key}' to be a string"
        raise ValueError(msg)
    return value


def _required_datetime(row: Mapping[str, Any], key: str) -> datetime:
    value = row.get(key)
    if not isinstance(value, datetime):
        msg = f"expected field '{key}' to be a datetime"
        raise ValueError(msg)
    return value


def _required_decimal(row: Mapping[str, Any], key: str) -> Decimal:
    value = row.get(key)
    if not isinstance(value, Decimal):
        msg = f"expected field '{key}' to be a Decimal"
        raise ValueError(msg)
    return value


def _optional_decimal(row: Mapping[str, Any], key: str) -> Decimal | None:
    value = row.get(key)
    if value is None:
        return None
    if not isinstance(value, Decimal):
        msg = f"expected field '{key}' to be a Decimal"
        raise ValueError(msg)
    return value

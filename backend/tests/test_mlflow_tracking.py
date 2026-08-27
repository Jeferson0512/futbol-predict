from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal

import httpx

from futpredict.evaluation.mlflow_tracking import MlflowRestClient, _ModelMetricRun


def test_mlflow_client_creates_experiment_when_missing() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("/experiments/get-by-name"):
            return httpx.Response(
                404,
                json={"error_code": "RESOURCE_DOES_NOT_EXIST"},
            )
        if request.url.path.endswith("/experiments/create"):
            return httpx.Response(200, json={"experiment_id": "42"})
        return httpx.Response(500, json={"error": "unexpected request"})

    client = MlflowRestClient(
        "http://mlflow.test",
        transport=httpx.MockTransport(handler),
    )

    try:
        assert client.get_or_create_experiment_id("Futbol Predict Baselines") == "42"
    finally:
        client.close()

    assert [request.url.path for request in requests] == [
        "/api/2.0/mlflow/experiments/get-by-name",
        "/api/2.0/mlflow/experiments/create",
    ]


def test_mlflow_client_logs_model_metric_run_payload() -> None:
    payloads: dict[str, dict[str, object]] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/runs/create"):
            payloads["create"] = json.loads(request.content.decode("utf-8"))
            return httpx.Response(
                200,
                json={
                    "run": {
                        "info": {
                            "run_id": "run-1",
                            "artifact_uri": "/mlflow/artifacts/42/run-1/artifacts",
                        }
                    }
                },
            )
        if request.url.path.endswith("/runs/log-batch"):
            payloads["log_batch"] = json.loads(request.content.decode("utf-8"))
            return httpx.Response(200, json={})
        if request.url.path.endswith("/runs/update"):
            payloads["update"] = json.loads(request.content.decode("utf-8"))
            return httpx.Response(200, json={})
        return httpx.Response(500, json={"error": "unexpected request"})

    client = MlflowRestClient(
        "http://mlflow.test",
        transport=httpx.MockTransport(handler),
    )
    row = _sample_model_metric_run()

    try:
        run_info = client.create_run(experiment_id="42", row=row)
        client.log_batch(run_id=run_info.run_id, row=row)
        client.finish_run(run_id=run_info.run_id, finished_at=row.evaluated_at)
    finally:
        client.close()

    assert run_info.artifact_uri == "/mlflow/artifacts/42/run-1/artifacts"
    assert payloads["create"]["run_name"] == "E0/club_elo/1617-1819/eval-1920"
    assert _payload_keys(payloads["log_batch"], "metrics") >= {
        "n_matches",
        "rps",
        "log_loss",
        "brier",
        "accuracy",
    }
    assert _payload_keys(payloads["log_batch"], "params") >= {
        "league_code",
        "model",
        "algorithm",
        "hyperparam_evaluation_mode",
    }
    assert _payload_keys(payloads["log_batch"], "tags") >= {
        "futpredict_model_version_id",
        "futpredict_model_metric_id",
        "futpredict_model",
    }
    assert payloads["update"]["status"] == "FINISHED"


def _sample_model_metric_run() -> _ModelMetricRun:
    return _ModelMetricRun(
        model_version_id=10,
        model_metric_id=20,
        league_code="E0",
        league_name="Premier League",
        model="club_elo",
        algorithm="external_elo",
        feature_set_version="baseline_walk_forward_v1",
        hyperparams={
            "evaluation_mode": "expanding_walk_forward",
            "evaluation_season": "1920",
            "train_start_season": "1617",
            "train_end_season": "1819",
        },
        trained_at=datetime(2026, 1, 1, tzinfo=UTC),
        train_window_start=datetime(2016, 8, 1, tzinfo=UTC),
        train_window_end=datetime(2019, 6, 1, tzinfo=UTC),
        artifact_uri=None,
        window_label="E0:1920",
        evaluated_at=datetime(2026, 1, 2, tzinfo=UTC),
        n_matches=380,
        rps=Decimal("0.20267600"),
        log_loss=Decimal("0.99581100"),
        brier=Decimal("0.59415600"),
        accuracy=Decimal("0.52490000"),
        calibration_error=None,
    )


def _payload_keys(payload: dict[str, object], section: str) -> set[str]:
    entries = payload.get(section)
    assert isinstance(entries, list)
    return {str(entry["key"]) for entry in entries if isinstance(entry, dict)}

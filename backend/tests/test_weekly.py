from __future__ import annotations

import types
from typing import Any

import pytest

from futpredict.jobs import weekly

_ALL_STEP_HELPERS = (
    "_ingest_results",
    "_ingest_espn",
    "_ingest_xg",
    "_rebuild_elo",
    "_rebuild_features",
    "_walk_forward_metrics",
    "_freeze_walk_forward_predictions",
    "_evaluate_predictions",
    "_build_calibration_bins",
    "_promote_champion",
    "_freeze_future_predictions",
    "_backup_database",
)


def test_plan_weekly_steps_order_with_ingest_and_future() -> None:
    assert weekly.plan_weekly_steps() == [
        "ingest_results",
        "ingest_espn",
        "ingest_xg",
        "rebuild_elo",
        "rebuild_features",
        "walk_forward_metrics",
        "freeze_walk_forward_predictions",
        "evaluate_predictions",
        "build_calibration_bins",
        "promote_champion",
        "freeze_future_predictions",
        "backup_database",
    ]


def test_plan_weekly_steps_can_skip_ingest_and_future() -> None:
    steps = weekly.plan_weekly_steps(
        include_ingest=False,
        include_espn_ingest=False,
        include_xg_ingest=False,
        include_future=False,
    )
    assert "ingest_results" not in steps
    assert "ingest_espn" not in steps
    assert "ingest_xg" not in steps
    assert "freeze_future_predictions" not in steps
    assert steps[0] == "rebuild_elo"
    assert steps[-1] == "backup_database"


def test_plan_daily_steps_is_light() -> None:
    steps = weekly.plan_daily_steps()
    # El diario refresca y evalua, pero no re-entrena ni baja football-data.
    assert steps == [
        "ingest_espn",
        "rebuild_elo",
        "rebuild_features",
        "evaluate_predictions",
        "freeze_future_predictions",
        "backup_database",
    ]
    for skip in ("walk_forward_metrics", "build_calibration_bins", "promote_champion", "ingest_xg"):
        assert skip not in steps


def test_daily_pipeline_config_disables_training() -> None:
    cfg = weekly.daily_pipeline_config()
    assert cfg.include_training is False
    assert cfg.include_ingest is False
    assert cfg.include_espn_ingest is True
    assert cfg.include_xg_ingest is False
    assert cfg.include_future is True
    # El diario tambien respalda: congela predicciones que no se pueden rehacer.
    assert cfg.include_backup is True


def test_plan_weekly_steps_can_skip_backup() -> None:
    steps = weekly.plan_weekly_steps(include_backup=False)

    assert "backup_database" not in steps
    assert steps[-1] == "freeze_future_predictions"


def test_run_weekly_pipeline_continues_when_backup_fails(monkeypatch: Any) -> None:
    calls: list[str] = []
    _patch_all_steps(monkeypatch, calls)

    def boom(*_args: Any, **_kwargs: Any) -> str:
        raise RuntimeError("pg_dump missing")

    monkeypatch.setattr(weekly, "_backup_database", boom)
    session = types.SimpleNamespace(rollback=lambda: calls.append("rollback"))

    results = weekly.run_weekly_pipeline(session, dry_run=True, logger=lambda _msg: None)  # type: ignore[arg-type]

    by_name = {result.name: result for result in results}
    # El backup es el ultimo paso y es best-effort: queda registrado como error
    # pero no invalida el trabajo ya commiteado del pipeline.
    assert by_name["backup_database"].status == "error"
    assert by_name["freeze_future_predictions"].status == "dry-run"


def _patch_all_steps(monkeypatch: Any, calls: list[str]) -> None:
    for name in _ALL_STEP_HELPERS:
        step_name = name

        def fake(*_args: Any, _step_name: str = step_name, **_kwargs: Any) -> str:
            calls.append(_step_name)
            return "ok"

        monkeypatch.setattr(weekly, name, fake)


def test_run_weekly_pipeline_runs_all_steps_in_order(monkeypatch: Any) -> None:
    calls: list[str] = []
    _patch_all_steps(monkeypatch, calls)
    session = types.SimpleNamespace(rollback=lambda: calls.append("rollback"))

    results = weekly.run_weekly_pipeline(session, dry_run=True, logger=lambda _msg: None)  # type: ignore[arg-type]

    assert [result.name for result in results] == weekly.plan_weekly_steps()
    assert all(result.status == "dry-run" for result in results)
    assert calls[:-1] == list(_ALL_STEP_HELPERS)
    assert calls[-1] == "rollback"


def test_run_weekly_pipeline_wraps_step_errors(monkeypatch: Any) -> None:
    calls: list[str] = []
    _patch_all_steps(monkeypatch, calls)

    def boom(*_args: Any, **_kwargs: Any) -> str:
        raise RuntimeError("boom")

    monkeypatch.setattr(weekly, "_walk_forward_metrics", boom)
    session = types.SimpleNamespace(rollback=lambda: calls.append("rollback"))

    with pytest.raises(weekly.WeeklyPipelineError) as exc_info:
        weekly.run_weekly_pipeline(session, dry_run=True, logger=lambda _msg: None)  # type: ignore[arg-type]

    assert exc_info.value.step == "walk_forward_metrics"
    # No debe continuar despues del paso fatal que falla.
    assert "_freeze_walk_forward_predictions" not in calls
    assert "rollback" not in calls


def test_run_weekly_pipeline_continues_when_ingest_fails(monkeypatch: Any) -> None:
    calls: list[str] = []
    _patch_all_steps(monkeypatch, calls)

    def boom(*_args: Any, **_kwargs: Any) -> str:
        raise RuntimeError("network down")

    monkeypatch.setattr(weekly, "_ingest_results", boom)
    session = types.SimpleNamespace(rollback=lambda: calls.append("rollback"))

    results = weekly.run_weekly_pipeline(session, dry_run=True, logger=lambda _msg: None)  # type: ignore[arg-type]

    by_name = {result.name: result for result in results}
    # La ingesta es best-effort: queda registrada como error pero el resto corre.
    assert by_name["ingest_results"].status == "error"
    assert "_rebuild_elo" in calls
    assert "_freeze_future_predictions" in calls
    assert calls[-1] == "rollback"

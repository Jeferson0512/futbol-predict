from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import httpx
from sqlalchemy.orm import Session

from futpredict.data.db_matches import load_match_results_from_db
from futpredict.data.football_data_uk_catalog import (
    DEFAULT_BIG_FIVE_END_SEASON,
    DEFAULT_BIG_FIVE_START_SEASON,
    big_five_division_codes,
    current_season_code,
)
from futpredict.evaluation.db_calibration import (
    build_calibration_from_predictions,
    upsert_calibration_bins,
)
from futpredict.evaluation.db_champion import promote_champion_by_rps
from futpredict.evaluation.db_future_predictions import freeze_future_predictions
from futpredict.evaluation.db_predictions import (
    evaluate_pending_predictions,
    freeze_walk_forward_predictions,
)
from futpredict.evaluation.db_walk_forward import upsert_walk_forward_metrics
from futpredict.evaluation.ml_walk_forward import run_ml_walk_forward
from futpredict.evaluation.walk_forward import (
    DEFAULT_INITIAL_TRAIN_SEASONS,
    run_expanding_walk_forward,
)
from futpredict.evaluation.walk_forward_predictions import (
    run_expanding_walk_forward_predictions,
)
from futpredict.features.db_features import (
    load_feature_matches_from_db,
    load_feature_payloads_from_db,
    upsert_feature_snapshots,
)
from futpredict.features.rolling import FEATURE_SET_VERSION, build_rolling_feature_snapshots
from futpredict.ingest.normalized import (
    build_normalized_batch,
    build_normalized_fixture_batch,
)
from futpredict.ingest.persistence import load_normalized_batch
from futpredict.ingest.providers.football_data_uk import (
    download_many,
    load_matches,
    load_weekly_fixtures,
)
from futpredict.models.persisted_elo import (
    build_elo_rating_snapshots,
    load_elo_matches_from_db,
    upsert_elo_rating_snapshots,
)

Logger = Callable[[str], None]


@dataclass(frozen=True)
class WeeklyStepResult:
    name: str
    status: str  # "ok" | "dry-run" | "error"
    detail: str


@dataclass(frozen=True)
class WeeklyPipelineConfig:
    start_season: str = DEFAULT_BIG_FIVE_START_SEASON
    end_season: str = DEFAULT_BIG_FIVE_END_SEASON
    initial_train_seasons: int = DEFAULT_INITIAL_TRAIN_SEASONS
    future_days: int = 14
    future_limit: int = 200
    champion_min_matches: int = 100
    include_ingest: bool = True
    include_future: bool = True
    ingest_season: str = field(default_factory=current_season_code)
    cache_dir: Path = Path("data/raw/football-data-uk")
    divisions: tuple[str, ...] = field(default_factory=lambda: tuple(big_five_division_codes()))


class WeeklyPipelineError(RuntimeError):
    def __init__(self, step: str, cause: Exception) -> None:
        super().__init__(f"weekly pipeline failed at step '{step}': {cause}")
        self.step = step
        self.cause = cause


def plan_weekly_steps(
    *,
    include_ingest: bool = True,
    include_future: bool = True,
) -> list[str]:
    """Orden canonico de pasos del pipeline semanal."""
    steps: list[str] = []
    if include_ingest:
        steps.append("ingest_results")
    steps += [
        "rebuild_elo",
        "rebuild_features",
        "walk_forward_metrics",
        "freeze_walk_forward_predictions",
        "evaluate_predictions",
        "build_calibration_bins",
        "promote_champion",
    ]
    if include_future:
        steps.append("freeze_future_predictions")
    return steps


def run_weekly_pipeline(
    session: Session,
    *,
    config: WeeklyPipelineConfig | None = None,
    dry_run: bool = False,
    logger: Logger = print,
    now: datetime | None = None,
) -> list[WeeklyStepResult]:
    """Ejecuta el pipeline semanal contra una sesion de base de datos.

    En ``dry_run`` cada paso calcula pero no escribe; el resto persiste y hace
    commit por paso, de modo que un fallo tardio no descarta el progreso previo.
    """
    cfg = config or WeeklyPipelineConfig()
    timestamp = now if now is not None else datetime.now(UTC)
    divisions = list(cfg.divisions)
    results: list[WeeklyStepResult] = []
    prefix = "[dry-run]" if dry_run else "[run]"

    def step(name: str, fn: Callable[[], str], *, fatal: bool = True) -> None:
        logger(f"{prefix} start {name}")
        try:
            detail = fn()
        except Exception as exc:  # noqa: BLE001 - re-lanzado con contexto de paso
            results.append(WeeklyStepResult(name=name, status="error", detail=repr(exc)))
            logger(f"{prefix} error {name}: {exc!r}")
            if fatal:
                raise WeeklyPipelineError(name, exc) from exc
            return
        status = "dry-run" if dry_run else "ok"
        results.append(WeeklyStepResult(name=name, status=status, detail=detail))
        logger(f"{prefix} {status} {name}: {detail}")

    if cfg.include_ingest:
        # La ingesta por red es best-effort: si falla, se registra y el pipeline
        # continua recalculando sobre los datos ya presentes en la base.
        step(
            "ingest_results",
            lambda: _ingest_results(session, cfg, divisions, dry_run),
            fatal=False,
        )
    step("rebuild_elo", lambda: _rebuild_elo(session, cfg, divisions, timestamp, dry_run))
    step("rebuild_features", lambda: _rebuild_features(session, cfg, divisions, dry_run))
    step("walk_forward_metrics", lambda: _walk_forward_metrics(session, cfg, divisions, dry_run))
    step(
        "freeze_walk_forward_predictions",
        lambda: _freeze_walk_forward_predictions(session, cfg, divisions, dry_run),
    )
    step("evaluate_predictions", lambda: _evaluate_predictions(session, dry_run))
    step("build_calibration_bins", lambda: _build_calibration_bins(session, dry_run))
    step("promote_champion", lambda: _promote_champion(session, cfg, dry_run))
    if cfg.include_future:
        step(
            "freeze_future_predictions",
            lambda: _freeze_future_predictions(session, cfg, divisions, timestamp, dry_run),
        )

    if dry_run:
        session.rollback()

    return results


def _ingest_results(
    session: Session,
    cfg: WeeklyPipelineConfig,
    divisions: list[str],
    dry_run: bool,
) -> str:
    # Resultados y fixtures se ingieren de forma independiente: si la temporada
    # actual todavia no publica el CSV de resultados, igual se cargan los
    # fixtures de la proxima jornada.
    season = cfg.ingest_season
    results_detail = _ingest_current_results(session, cfg, divisions, season, dry_run)
    fixtures_detail = _ingest_weekly_fixtures(session, cfg, divisions, season, dry_run)
    return f"season={season} {results_detail} {fixtures_detail}"


def _ingest_current_results(
    session: Session,
    cfg: WeeklyPipelineConfig,
    divisions: list[str],
    season: str,
    dry_run: bool,
) -> str:
    try:
        download_many(
            seasons=[season],
            divisions=divisions,
            cache_dir=cfg.cache_dir,
            force=True,
        )
        result_matches = load_matches(
            seasons=[season],
            divisions=divisions,
            cache_dir=cfg.cache_dir,
        )
    except (httpx.HTTPError, ValueError, OSError) as exc:
        return f"result_matches=skipped({exc.__class__.__name__})"

    if dry_run:
        return f"result_matches={len(result_matches)}"
    summary = load_normalized_batch(session, build_normalized_batch(result_matches))
    return f"result_matches={summary.matches}"


def _ingest_weekly_fixtures(
    session: Session,
    cfg: WeeklyPipelineConfig,
    divisions: list[str],
    season: str,
    dry_run: bool,
) -> str:
    try:
        fixtures = load_weekly_fixtures(
            season=season,
            divisions=divisions,
            cache_dir=cfg.cache_dir,
            force=True,
        )
    except (httpx.HTTPError, ValueError, OSError) as exc:
        return f"fixtures=skipped({exc.__class__.__name__})"

    if dry_run:
        return f"fixtures={len(fixtures)}"
    summary = load_normalized_batch(session, build_normalized_fixture_batch(fixtures))
    return f"fixtures={summary.matches}"


def _rebuild_elo(
    session: Session,
    cfg: WeeklyPipelineConfig,
    divisions: list[str],
    timestamp: datetime,
    dry_run: bool,
) -> str:
    elo_matches = load_elo_matches_from_db(
        session,
        start_season=cfg.start_season,
        end_season=cfg.end_season,
        division_codes=divisions,
    )
    snapshots = build_elo_rating_snapshots(elo_matches)
    if not dry_run:
        upsert_elo_rating_snapshots(session, snapshots)
    return f"matches={len(elo_matches)} ratings={len(snapshots)}"


def _rebuild_features(
    session: Session,
    cfg: WeeklyPipelineConfig,
    divisions: list[str],
    dry_run: bool,
) -> str:
    feature_matches = load_feature_matches_from_db(
        session,
        start_season=cfg.start_season,
        end_season=cfg.end_season,
        division_codes=divisions,
    )
    snapshots = build_rolling_feature_snapshots(feature_matches)
    if not dry_run:
        upsert_feature_snapshots(session, snapshots)
    return f"matches={len(feature_matches)} features={len(snapshots)}"


def _walk_forward_metrics(
    session: Session,
    cfg: WeeklyPipelineConfig,
    divisions: list[str],
    dry_run: bool,
) -> str:
    matches = load_match_results_from_db(
        session,
        start_season=cfg.start_season,
        end_season=cfg.end_season,
        division_codes=divisions,
    )
    metrics = run_expanding_walk_forward(
        matches,
        start_season=cfg.start_season,
        end_season=cfg.end_season,
        initial_train_seasons=cfg.initial_train_seasons,
    )
    payloads = load_feature_payloads_from_db(
        session,
        feature_set_version=FEATURE_SET_VERSION,
        start_season=cfg.start_season,
        end_season=cfg.end_season,
        division_codes=divisions,
    )
    ml_metrics = run_ml_walk_forward(
        matches,
        payloads,
        start_season=cfg.start_season,
        end_season=cfg.end_season,
        initial_train_seasons=cfg.initial_train_seasons,
    )
    metrics = [*metrics, *ml_metrics]
    if not dry_run:
        summary = upsert_walk_forward_metrics(session, metrics)
        return (
            f"model_versions={summary.model_versions} metrics={summary.metrics} "
            f"ml_windows={len(ml_metrics)}"
        )
    return f"metrics={len(metrics)} ml_windows={len(ml_metrics)}"


def _freeze_walk_forward_predictions(
    session: Session,
    cfg: WeeklyPipelineConfig,
    divisions: list[str],
    dry_run: bool,
) -> str:
    matches = load_match_results_from_db(
        session,
        start_season=cfg.start_season,
        end_season=cfg.end_season,
        division_codes=divisions,
    )
    predictions = run_expanding_walk_forward_predictions(
        matches,
        start_season=cfg.start_season,
        end_season=cfg.end_season,
        initial_train_seasons=cfg.initial_train_seasons,
    )
    if not dry_run:
        summary = freeze_walk_forward_predictions(session, predictions)
        return (
            f"candidates={summary.candidates} "
            f"inserted={summary.inserted_predictions} existing={summary.existing_predictions}"
        )
    return f"candidates={len(predictions)}"


def _evaluate_predictions(session: Session, dry_run: bool) -> str:
    summary = evaluate_pending_predictions(session, commit=not dry_run)
    return f"evaluated={summary.evaluated_predictions}"


def _build_calibration_bins(session: Session, dry_run: bool) -> str:
    calibration = build_calibration_from_predictions(session, n_bins=10)
    if not dry_run:
        summary = upsert_calibration_bins(session, calibration)
        return f"bins={summary.bins} model_versions={summary.model_versions}"
    return f"bins={len(calibration.bins)}"


def _promote_champion(session: Session, cfg: WeeklyPipelineConfig, dry_run: bool) -> str:
    summary = promote_champion_by_rps(
        session,
        min_matches=cfg.champion_min_matches,
        commit=not dry_run,
    )
    if summary.champion_model is None:
        return "champion=none"
    rps = f"{summary.weighted_rps:.6f}" if summary.weighted_rps is not None else "n/a"
    return (
        f"champion={summary.champion_model} rps={rps} "
        f"promoted={summary.promoted_versions} demoted={summary.demoted_versions}"
    )


def _freeze_future_predictions(
    session: Session,
    cfg: WeeklyPipelineConfig,
    divisions: list[str],
    timestamp: datetime,
    dry_run: bool,
) -> str:
    summary = freeze_future_predictions(
        session,
        frozen_at=timestamp,
        days=cfg.future_days,
        division_codes=divisions,
        limit=cfg.future_limit,
        commit=not dry_run,
    )
    return (
        f"eligible_fixtures={summary.eligible_fixtures} "
        f"candidates={summary.candidates} inserted={summary.inserted_predictions} "
        f"existing={summary.existing_predictions}"
    )


if __name__ == "__main__":  # pragma: no cover - ejecucion manual
    from futpredict.db.session import SessionLocal

    with SessionLocal() as _session:
        for _result in run_weekly_pipeline(_session, dry_run=True):
            pass

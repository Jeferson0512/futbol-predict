from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path

import httpx
from sqlalchemy.orm import Session

from futpredict.data.db_espn_europe import load_all_espn_europe
from futpredict.data.db_matches import league_codes_from_divisions, load_match_results_from_db
from futpredict.data.db_peru import load_peru_matches
from futpredict.data.db_understat import store_understat_xg
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
from futpredict.evaluation.ml_walk_forward import (
    ml_models_for_keys,
    run_configured_ml_walk_forward,
)
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
from futpredict.features.rolling import (
    FEATURE_SET_VERSION,
    FEATURE_SET_VERSION_V2,
    build_rolling_feature_snapshots,
)
from futpredict.ingest.normalized import (
    build_normalized_batch,
    build_normalized_fixture_batch,
)
from futpredict.ingest.persistence import load_normalized_batch
from futpredict.ingest.providers.espn_peru import (
    PERU_DIVISION,
    fetch_espn_peru_season,
)
from futpredict.ingest.providers.football_data_uk import (
    download_many,
    load_matches,
    load_weekly_fixtures,
)
from futpredict.ingest.providers.understat import fetch_understat_xg
from futpredict.models.persisted_elo import (
    build_elo_rating_snapshots,
    load_elo_matches_from_db,
    upsert_elo_rating_snapshots,
)
from futpredict.models.tabular import FEATURE_KEYS_V2

Logger = Callable[[str], None]


def current_europe_season_start_year(today: date | None = None) -> int:
    """Ano de inicio de la temporada europea en curso (2026 = 2026/27)."""
    today = today or datetime.now(UTC).date()
    return today.year if today.month >= 7 else today.year - 1


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
    include_espn_ingest: bool = True
    include_peru_ingest: bool = True
    include_xg_ingest: bool = True
    include_training: bool = True
    include_future: bool = True
    ingest_season: str = field(default_factory=current_season_code)
    espn_season_start_year: int = field(default_factory=current_europe_season_start_year)
    peru_year: int = field(default_factory=lambda: datetime.now(UTC).year)
    espn_europe_divisions: tuple[str, ...] = ("E0", "SP1", "I1", "D1", "F1")
    # Temporadas cuyo xG se refresca desde Understat. El historico es estatico
    # (se carga una vez con load-understat-xg-big-five); el semanal mantiene solo
    # la temporada en curso.
    xg_seasons: tuple[str, ...] = field(default_factory=lambda: (current_season_code(),))
    xg_cache_dir: Path = Path("data/raw/understat")
    cache_dir: Path = Path("data/raw/football-data-uk")
    # Divisiones de entrenamiento (football-data: cuotas/xG). Solo Big-5.
    divisions: tuple[str, ...] = field(default_factory=lambda: tuple(big_five_division_codes()))
    # Divisiones que se sirven al usuario (Elo/features/freeze). Big-5 + Peru;
    # cada liga mantiene su propia escala, no se contaminan entre si.
    serving_divisions: tuple[str, ...] = field(
        default_factory=lambda: (*big_five_division_codes(), PERU_DIVISION)
    )


class WeeklyPipelineError(RuntimeError):
    def __init__(self, step: str, cause: Exception) -> None:
        super().__init__(f"weekly pipeline failed at step '{step}': {cause}")
        self.step = step
        self.cause = cause


def plan_weekly_steps(
    *,
    include_ingest: bool = True,
    include_espn_ingest: bool = True,
    include_xg_ingest: bool = True,
    include_training: bool = True,
    include_future: bool = True,
) -> list[str]:
    """Orden canonico de pasos del pipeline.

    El job **semanal** corre todo (``include_training=True``): re-entrena
    walk-forward (con xG), recalibra y promueve campeon. El job **diario** es
    ligero (``include_training=False``): solo refresca resultados, Elo/features y
    evalua/congela, sin re-entrenar ni raspar xG de Understat.
    """
    steps: list[str] = []
    if include_ingest:
        steps.append("ingest_results")
    if include_espn_ingest:
        steps.append("ingest_espn")
    if include_xg_ingest:
        steps.append("ingest_xg")
    steps += ["rebuild_elo", "rebuild_features"]
    if include_training:
        steps += ["walk_forward_metrics", "freeze_walk_forward_predictions"]
    steps.append("evaluate_predictions")
    if include_training:
        steps += ["build_calibration_bins", "promote_champion"]
    if include_future:
        steps.append("freeze_future_predictions")
    return steps


def plan_daily_steps() -> list[str]:
    """Pasos del job diario ligero (sin football-data, xG ni re-entrenamiento)."""
    return plan_weekly_steps(
        include_ingest=False,
        include_xg_ingest=False,
        include_training=False,
    )


def daily_pipeline_config(**overrides: object) -> WeeklyPipelineConfig:
    """Config del job diario: ESPN + Elo/features + evaluar + congelar futuras.

    Se apoya en el campeon ya promovido por el semanal; no re-entrena, no baja
    los CSV de football-data ni raspa xG (ESPN cubre la temporada en curso; el
    xG lo refresca el semanal).
    """
    base: dict[str, object] = {
        "include_ingest": False,
        "include_espn_ingest": True,
        "include_xg_ingest": False,
        "include_training": False,
        "include_future": True,
    }
    base.update(overrides)
    return WeeklyPipelineConfig(**base)  # type: ignore[arg-type]


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
    serving = list(cfg.serving_divisions)
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
    if cfg.include_espn_ingest:
        # ESPN cubre la temporada en curso (Europa + Peru) que football-data
        # aun no publica. Tambien best-effort.
        step("ingest_espn", lambda: _ingest_espn(session, cfg, dry_run), fatal=False)
    if cfg.include_xg_ingest:
        # xG de Understat para la temporada en curso (scraping best-effort).
        step("ingest_xg", lambda: _ingest_xg(session, cfg, divisions, dry_run), fatal=False)
    step("rebuild_elo", lambda: _rebuild_elo(session, cfg, serving, timestamp, dry_run))
    step("rebuild_features", lambda: _rebuild_features(session, cfg, serving, dry_run))
    if cfg.include_training:
        step(
            "walk_forward_metrics",
            lambda: _walk_forward_metrics(session, cfg, divisions, dry_run),
        )
        step(
            "freeze_walk_forward_predictions",
            lambda: _freeze_walk_forward_predictions(session, cfg, divisions, dry_run),
        )
    step("evaluate_predictions", lambda: _evaluate_predictions(session, dry_run))
    if cfg.include_training:
        step("build_calibration_bins", lambda: _build_calibration_bins(session, dry_run))
        step("promote_champion", lambda: _promote_champion(session, cfg, dry_run))
    if cfg.include_future:
        step(
            "freeze_future_predictions",
            lambda: _freeze_future_predictions(session, cfg, serving, timestamp, dry_run),
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


def _ingest_espn(
    session: Session,
    cfg: WeeklyPipelineConfig,
    dry_run: bool,
) -> str:
    # Refresca la temporada en curso desde ESPN: vuelca partidos jugados a
    # "finished" con su marcador y agrega los fixtures nuevos. Idempotente.
    parts: list[str] = []

    try:
        europe = load_all_espn_europe(
            session,
            season_start_year=cfg.espn_season_start_year,
            divisions=cfg.espn_europe_divisions,
            commit=not dry_run,
        )
        loaded = sum(item.loaded for item in europe)
        finished = sum(item.finished for item in europe)
        parts.append(f"europe_loaded={loaded} europe_finished={finished}")
    except (httpx.HTTPError, ValueError, OSError) as exc:
        parts.append(f"europe=skipped({exc.__class__.__name__})")

    if cfg.include_peru_ingest:
        try:
            peru_matches = fetch_espn_peru_season(cfg.peru_year)
            if dry_run:
                parts.append(f"peru_fetched={len(peru_matches)}")
            else:
                peru = load_peru_matches(session, peru_matches, commit=True)
                parts.append(f"peru_loaded={peru.matches} peru_finished={peru.finished}")
        except (httpx.HTTPError, ValueError, OSError) as exc:
            parts.append(f"peru=skipped({exc.__class__.__name__})")

    return " ".join(parts)


def _ingest_xg(
    session: Session,
    cfg: WeeklyPipelineConfig,
    divisions: list[str],
    dry_run: bool,
) -> str:
    # Refresca xG de Understat para las temporadas en curso (Big-5). El historico
    # es estatico y se carga una vez; aqui solo se mantiene lo nuevo. Empareja por
    # (temporada, equipos normalizados) y escribe home_xg/away_xg. Best-effort:
    # si Understat falla para una liga/temporada, se salta esa y sigue.
    updated = 0
    skipped = 0
    for division in divisions:
        league_code = league_codes_from_divisions([division])[0]
        for season in cfg.xg_seasons:
            our_matches = load_match_results_from_db(
                session,
                start_season=season,
                end_season=season,
                division_codes=[division],
            )
            if not our_matches:
                continue
            try:
                understat_matches = fetch_understat_xg(
                    league_code=league_code,
                    season=season,
                    cache_dir=cfg.xg_cache_dir,
                )
            except Exception:  # noqa: BLE001 - red/scraping de Understat, best-effort
                skipped += 1
                continue
            summary = store_understat_xg(
                session, understat_matches, our_matches, commit=not dry_run
            )
            updated += summary.updated
    return f"seasons={list(cfg.xg_seasons)} xg_updated={updated} skipped_fetches={skipped}"


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
    # V1 (base) para compatibilidad y V2 (con xG) que consume el ML del semanal y
    # el detalle de partido (/matches/{id}). Cada match tiene su xG (o None) ya en
    # la tabla, asi que V2 lo aprovecha donde exista.
    snapshots_v1 = build_rolling_feature_snapshots(
        feature_matches,
        feature_set_version=FEATURE_SET_VERSION,
    )
    snapshots_v2 = build_rolling_feature_snapshots(
        feature_matches,
        feature_set_version=FEATURE_SET_VERSION_V2,
        include_xg=True,
    )
    if not dry_run:
        upsert_feature_snapshots(session, snapshots_v1)
        upsert_feature_snapshots(session, snapshots_v2)
    return f"matches={len(feature_matches)} v1={len(snapshots_v1)} v2={len(snapshots_v2)}"


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
    # ML entrena sobre V2 (rolling_v1 + xG); el imputer de la logistica y el
    # soporte NaN-nativo del boosting cubren los partidos sin xG.
    payloads = load_feature_payloads_from_db(
        session,
        feature_set_version=FEATURE_SET_VERSION_V2,
        start_season=cfg.start_season,
        end_season=cfg.end_season,
        division_codes=divisions,
    )
    ml_metrics = run_configured_ml_walk_forward(
        matches,
        payloads,
        start_season=cfg.start_season,
        end_season=cfg.end_season,
        initial_train_seasons=cfg.initial_train_seasons,
        models=ml_models_for_keys(FEATURE_KEYS_V2),
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
    if not summary.champions:
        return "champions=none"
    detail = " ".join(f"{c.league_code}:{c.model}" for c in summary.champions)
    return (
        f"champions={len(summary.champions)} promoted={summary.promoted_versions} "
        f"demoted={summary.demoted_versions} [{detail}]"
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

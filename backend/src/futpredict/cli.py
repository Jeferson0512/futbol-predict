from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import httpx
import typer
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from futpredict.data.db_matches import (
    league_codes_from_divisions,
    load_match_results_from_db,
)
from futpredict.data.db_understat import UnderstatStoreSummary, store_understat_xg
from futpredict.data.football_data_uk_catalog import (
    DEFAULT_BIG_FIVE_END_SEASON,
    DEFAULT_BIG_FIVE_START_SEASON,
    big_five_division_codes,
    current_season_code,
    season_range,
)
from futpredict.domain.matches import MatchResult
from futpredict.evaluation.backtest import MetricSummary, PredictionProvider, backtest_summary
from futpredict.evaluation.db_calibration import (
    CalibrationBuild,
    CalibrationPersistenceSummary,
    build_calibration_from_predictions,
    calibration_status_rows,
    upsert_calibration_bins,
)
from futpredict.evaluation.db_champion import (
    ChampionPromotionSummary,
    champion_status_rows,
    promote_champion_by_rps,
)
from futpredict.evaluation.db_future_predictions import (
    FuturePredictionFreezeSummary,
    freeze_future_predictions,
)
from futpredict.evaluation.db_predictions import (
    PredictionEvaluationSummary,
    PredictionPersistenceSummary,
    evaluate_pending_predictions,
    freeze_walk_forward_predictions,
    prediction_status_rows,
)
from futpredict.evaluation.db_walk_forward import (
    WalkForwardPersistenceSummary,
    upsert_walk_forward_metrics,
)
from futpredict.evaluation.ml_walk_forward import (
    ml_models_for_keys,
    run_configured_ml_walk_forward,
)
from futpredict.evaluation.mlflow_tracking import (
    DEFAULT_MLFLOW_EXPERIMENT_NAME,
    MlflowSyncSummary,
    sync_model_versions_to_mlflow,
)
from futpredict.evaluation.walk_forward import (
    DEFAULT_INITIAL_TRAIN_SEASONS,
    WalkForwardMetric,
    run_expanding_walk_forward,
    summarize_walk_forward_metrics,
)
from futpredict.evaluation.walk_forward_predictions import (
    WalkForwardPrediction,
    run_expanding_walk_forward_predictions,
)
from futpredict.features.db_features import (
    FeaturePersistenceSummary,
    load_feature_matches_from_db,
    load_feature_payloads_from_db,
    upsert_feature_snapshots,
)
from futpredict.features.rolling import (
    FEATURE_SET_VERSION,
    FEATURE_SET_VERSION_V2,
    FeatureMatch,
    FeatureSnapshot,
    build_rolling_feature_snapshots,
)
from futpredict.ingest.normalized import (
    NormalizedBatch,
    build_normalized_batch,
    build_normalized_fixture_batch,
    summarize_normalized_batch,
    validate_normalized_batch,
)
from futpredict.ingest.persistence import PersistenceSummary, load_normalized_batch
from futpredict.ingest.providers.football_data_uk import (
    download_csv,
    download_fixtures_csv,
    download_many,
    fetch_csv,
    load_matches,
    load_weekly_fixtures,
    parse_matches,
    read_csv_file,
)
from futpredict.ingest.providers.understat import (
    UnderstatMatchXg,
    fetch_understat_xg,
    understat_xg_coverage,
)
from futpredict.jobs.weekly import (
    WeeklyPipelineConfig,
    WeeklyPipelineError,
    run_weekly_pipeline,
)
from futpredict.models.club_elo import (
    ClubEloPredictionCoverage,
    ClubEloPredictor,
    load_club_elo_predictor_for_matches,
)
from futpredict.models.persisted_elo import (
    ELO_RATING_SYSTEM,
    EloMatch,
    EloPersistenceSummary,
    EloRatingSnapshot,
    build_elo_rating_snapshots,
    load_elo_matches_from_db,
    upsert_elo_rating_snapshots,
)
from futpredict.models.tabular import FEATURE_KEYS, FEATURE_KEYS_V2

app = typer.Typer(help="Herramientas locales del proyecto Futbol Predict.")


@app.command("export-openapi")
def export_openapi(
    output: Path = typer.Option(
        Path("../frontend/src/api/openapi.json"),
        help="Ruta de salida para el schema OpenAPI JSON.",
    ),
) -> None:
    from futpredict.main import create_app

    schema = create_app().openapi()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(schema, ensure_ascii=True, indent=2), encoding="utf-8")
    typer.echo(str(output))


@app.command("ingest-football-data-uk")
def ingest_football_data_uk(
    season: str = typer.Option(..., help="Codigo de temporada, por ejemplo 2526."),
    division: str = typer.Option(..., help="Codigo de liga, por ejemplo E0, SP1, I1, D1, F1."),
) -> None:
    frame = fetch_csv(season=season, division=division)
    typer.echo(f"Downloaded {len(frame)} rows from football-data.co.uk ({season}/{division}).")
    typer.echo(", ".join(frame.columns[:12]))


@app.command("download-football-data-uk")
def download_football_data_uk(
    season: str = typer.Option(..., help="Codigo de temporada, por ejemplo 2526."),
    division: str = typer.Option(..., help="Codigo de liga, por ejemplo E0."),
    cache_dir: Path = typer.Option(
        Path("data/raw/football-data-uk"),
        help="Carpeta de cache local.",
    ),
    force: bool = typer.Option(False, help="Descargar aunque el CSV ya exista."),
) -> None:
    path = download_csv(season=season, division=division, cache_dir=cache_dir, force=force)
    typer.echo(str(path))


@app.command("download-football-data-uk-fixtures")
def download_football_data_uk_fixtures(
    cache_dir: Path = typer.Option(
        Path("data/raw/football-data-uk"),
        help="Carpeta de cache local.",
    ),
    force: bool = typer.Option(True, help="Descargar aunque el CSV ya exista."),
) -> None:
    path = download_fixtures_csv(cache_dir=cache_dir, force=force)
    typer.echo(str(path))


@app.command("backtest-football-data-uk")
def backtest_football_data_uk(
    season: str = typer.Option(..., help="Codigo de temporada, por ejemplo 2526."),
    division: str = typer.Option(..., help="Codigo de liga, por ejemplo E0."),
    cache_dir: Path = typer.Option(
        Path("data/raw/football-data-uk"),
        help="Carpeta de cache local.",
    ),
) -> None:
    csv_path = download_csv(season=season, division=division, cache_dir=cache_dir)
    frame = read_csv_file(csv_path, season=season, division=division)
    matches = parse_matches(frame, season=season, division=division)
    summaries = backtest_summary(matches)

    typer.echo(f"Backtest {division.upper()} {season} - {len(matches)} matches")
    typer.echo("model,n_matches,rps,log_loss,brier,accuracy")
    for summary in summaries:
        typer.echo(
            f"{summary.model},{summary.n_matches},{summary.rps:.6f},"
            f"{summary.log_loss:.6f},{summary.brier:.6f},{summary.accuracy:.4f}"
        )


@app.command("download-big-five")
def download_big_five(
    start_season: str = typer.Option(
        DEFAULT_BIG_FIVE_START_SEASON,
        help="Temporada inicial, por ejemplo 1617.",
    ),
    end_season: str = typer.Option(
        DEFAULT_BIG_FIVE_END_SEASON,
        help="Temporada final, por ejemplo 2526.",
    ),
    cache_dir: Path = typer.Option(
        Path("data/raw/football-data-uk"),
        help="Carpeta de cache local.",
    ),
    force: bool = typer.Option(False, help="Descargar aunque el CSV ya exista."),
) -> None:
    seasons = season_range(start_season, end_season)
    divisions = big_five_division_codes()
    paths = download_many(seasons=seasons, divisions=divisions, cache_dir=cache_dir, force=force)
    typer.echo(f"Downloaded or reused {len(paths)} CSV files.")


@app.command("backtest-big-five")
def backtest_big_five(
    start_season: str = typer.Option(
        DEFAULT_BIG_FIVE_START_SEASON,
        help="Temporada inicial, por ejemplo 1617.",
    ),
    end_season: str = typer.Option(
        DEFAULT_BIG_FIVE_END_SEASON,
        help="Temporada final, por ejemplo 2526.",
    ),
    cache_dir: Path = typer.Option(
        Path("data/raw/football-data-uk"),
        help="Carpeta de cache local.",
    ),
) -> None:
    seasons = season_range(start_season, end_season)
    divisions = big_five_division_codes()
    matches = load_matches(seasons=seasons, divisions=divisions, cache_dir=cache_dir)
    summaries = backtest_summary(matches)

    typer.echo(
        f"Backtest Big-5 {start_season}-{end_season} - "
        f"{len(matches)} matches across {len(divisions)} divisions"
    )
    typer.echo("model,n_matches,rps,log_loss,brier,accuracy")
    for summary in summaries:
        typer.echo(
            f"{summary.model},{summary.n_matches},{summary.rps:.6f},"
            f"{summary.log_loss:.6f},{summary.brier:.6f},{summary.accuracy:.4f}"
        )


@app.command("backtest-db-football-data-uk")
def backtest_db_football_data_uk(
    season: str = typer.Option(..., help="Codigo de temporada, por ejemplo 2526."),
    division: str = typer.Option(..., help="Codigo de liga, por ejemplo E0."),
) -> None:
    normalized_division = division.upper()
    matches = _load_db_match_results(
        start_season=season,
        end_season=season,
        divisions=[normalized_division],
    )
    summaries = _backtest_summaries_or_exit(matches)

    typer.echo(f"Backtest DB {normalized_division} {season} - {len(matches)} matches")
    _echo_metric_csv(summaries)


@app.command("backtest-db-big-five")
def backtest_db_big_five(
    start_season: str = typer.Option(
        DEFAULT_BIG_FIVE_START_SEASON,
        help="Temporada inicial, por ejemplo 1617.",
    ),
    end_season: str = typer.Option(
        DEFAULT_BIG_FIVE_END_SEASON,
        help="Temporada final, por ejemplo 2526.",
    ),
) -> None:
    divisions = big_five_division_codes()
    matches = _load_db_match_results(
        start_season=start_season,
        end_season=end_season,
        divisions=divisions,
    )
    summaries = _backtest_summaries_or_exit(matches)

    typer.echo(
        f"Backtest DB Big-5 {start_season}-{end_season} - "
        f"{len(matches)} matches across {len(divisions)} divisions"
    )
    _echo_metric_csv(summaries)


@app.command("walk-forward-db")
def walk_forward_db(
    start_season: str = typer.Option(
        DEFAULT_BIG_FIVE_START_SEASON,
        help="Temporada inicial, por ejemplo 1617.",
    ),
    end_season: str = typer.Option(
        DEFAULT_BIG_FIVE_END_SEASON,
        help="Temporada final, por ejemplo 2526.",
    ),
    initial_train_seasons: int = typer.Option(
        DEFAULT_INITIAL_TRAIN_SEASONS,
        help="Cantidad de temporadas iniciales usadas como entrenamiento historico.",
    ),
    include_club_elo: bool = typer.Option(
        False,
        help="Incluir benchmark externo de Club Elo usando cache local.",
    ),
    club_elo_cache_dir: Path = typer.Option(
        Path("data/raw/clubelo"),
        help="Carpeta de cache local para historiales Club Elo.",
    ),
    force_club_elo: bool = typer.Option(
        False,
        help="Descargar historiales Club Elo aunque ya existan en cache.",
    ),
    club_elo_timeout: float = typer.Option(
        30.0,
        help="Timeout por solicitud a Club Elo, en segundos.",
    ),
    club_elo_workers: int = typer.Option(
        6,
        help="Descargas paralelas maximas para historiales Club Elo.",
    ),
    club_elo_offline: bool = typer.Option(
        False,
        help="Usar solo cache local de Club Elo, sin descargar.",
    ),
    include_ml: bool = typer.Option(
        True,
        help="Incluir el modelo ML (regresion logistica) sobre features rolling_v1.",
    ),
    dry_run: bool = typer.Option(False, help="Calcular walk-forward sin escribir metricas."),
) -> None:
    divisions = big_five_division_codes()
    matches = _load_db_match_results(
        start_season=start_season,
        end_season=end_season,
        divisions=divisions,
    )
    extra_providers = None
    if include_club_elo:
        club_elo_predictor = _load_club_elo_predictor_or_exit(
            matches,
            cache_dir=club_elo_cache_dir,
            force=force_club_elo,
            timeout=club_elo_timeout,
            max_workers=club_elo_workers,
            allow_download=not club_elo_offline,
        )
        extra_providers = (club_elo_predictor,)
    metrics = _run_walk_forward_or_exit(
        matches,
        start_season=start_season,
        end_season=end_season,
        initial_train_seasons=initial_train_seasons,
        extra_prediction_providers=extra_providers,
    )
    if include_ml:
        metrics = [
            *metrics,
            *_run_ml_walk_forward_or_exit(
                matches,
                start_season=start_season,
                end_season=end_season,
                initial_train_seasons=initial_train_seasons,
            ),
        ]
    _echo_walk_forward_summary(metrics)
    if dry_run:
        typer.echo("Dry run: no database writes executed.")
        return
    _persist_walk_forward_metrics(metrics)


@app.command("understat-xg-coverage")
def understat_xg_coverage_command(
    division: str = typer.Option(..., help="Codigo de liga, por ejemplo E0."),
    season: str = typer.Option(..., help="Codigo de temporada, por ejemplo 2324."),
    cache_dir: Path = typer.Option(
        Path("data/raw/understat"),
        help="Carpeta de cache local para soccerdata/Understat.",
    ),
) -> None:
    division_code = division.upper()
    league_codes = league_codes_from_divisions([division_code])
    if not league_codes:
        typer.echo(f"no hay liga para la division {division_code}", err=True)
        raise typer.Exit(1)
    league_code = league_codes[0]

    matches = _load_db_match_results(
        start_season=season,
        end_season=season,
        divisions=[division_code],
    )
    db_fixtures = [(match.home_team, match.away_team) for match in matches]

    try:
        understat_matches = fetch_understat_xg(
            league_code=league_code,
            season=season,
            cache_dir=cache_dir,
        )
    except Exception as exc:  # noqa: BLE001 - diagnostico: red/scraping de Understat
        typer.echo(f"Understat fetch failed: {exc.__class__.__name__}: {exc}", err=True)
        raise typer.Exit(1) from exc

    coverage = understat_xg_coverage(
        db_fixtures,
        understat_matches,
        league_code=league_code,
        season=season,
    )
    typer.echo("Understat xG coverage")
    typer.echo(f"league={coverage.league_code} season={coverage.season}")
    typer.echo(f"understat_matches={coverage.understat_matches}")
    typer.echo(f"db_matches={coverage.db_matches}")
    typer.echo(f"matched={coverage.matched}")
    typer.echo(f"coverage={coverage.coverage_ratio:.4f}")
    if coverage.unmatched_understat_teams:
        typer.echo(
            "unmatched_understat_teams=" + ", ".join(coverage.unmatched_understat_teams)
        )


@app.command("load-understat-xg-big-five")
def load_understat_xg_big_five(
    start_season: str = typer.Option(
        DEFAULT_BIG_FIVE_START_SEASON,
        help="Temporada inicial, por ejemplo 1617.",
    ),
    end_season: str = typer.Option(
        DEFAULT_BIG_FIVE_END_SEASON,
        help="Temporada final, por ejemplo 2526.",
    ),
    cache_dir: Path = typer.Option(
        Path("data/raw/understat"),
        help="Carpeta de cache local para soccerdata/Understat.",
    ),
    dry_run: bool = typer.Option(
        False,
        help="Solo sondear cobertura y equipos sin mapear, sin escribir xG.",
    ),
) -> None:
    divisions = big_five_division_codes()
    seasons = season_range(start_season, end_season)
    unmatched_teams: set[str] = set()
    total_updated = 0
    typer.echo("division,season,understat,db,matched_or_updated,unmatched")
    for division in divisions:
        league_code = league_codes_from_divisions([division])[0]
        for season in seasons:
            matches = _load_db_match_results(
                start_season=season,
                end_season=season,
                divisions=[division],
            )
            try:
                understat_matches = fetch_understat_xg(
                    league_code=league_code,
                    season=season,
                    cache_dir=cache_dir,
                )
            except Exception as exc:  # noqa: BLE001 - red/scraping de Understat
                typer.echo(f"{division},{season},ERROR,{exc.__class__.__name__}", err=True)
                continue

            if dry_run:
                coverage = understat_xg_coverage(
                    [(match.home_team, match.away_team) for match in matches],
                    understat_matches,
                    league_code=league_code,
                    season=season,
                )
                unmatched_teams.update(coverage.unmatched_understat_teams)
                typer.echo(
                    f"{division},{season},{coverage.understat_matches},"
                    f"{coverage.db_matches},{coverage.matched},"
                    f"{len(coverage.unmatched_understat_teams)}"
                )
            else:
                summary = _store_understat_xg_or_exit(understat_matches, matches)
                total_updated += summary.updated
                typer.echo(
                    f"{division},{season},{summary.understat_matches},"
                    f"{summary.db_matches},{summary.updated},{summary.unmatched}"
                )

    if unmatched_teams:
        typer.echo(
            "unmatched_understat_teams=" + ", ".join(sorted(unmatched_teams)),
            err=True,
        )
    if not dry_run:
        typer.echo(f"total_updated={total_updated}")


@app.command("backtest-ml-walk-forward-db")
def backtest_ml_walk_forward_db(
    start_season: str = typer.Option(
        DEFAULT_BIG_FIVE_START_SEASON,
        help="Temporada inicial, por ejemplo 1617.",
    ),
    end_season: str = typer.Option(
        DEFAULT_BIG_FIVE_END_SEASON,
        help="Temporada final, por ejemplo 2526.",
    ),
    initial_train_seasons: int = typer.Option(
        DEFAULT_INITIAL_TRAIN_SEASONS,
        help="Temporadas iniciales usadas como entrenamiento historico.",
    ),
    feature_set: str = typer.Option(
        FEATURE_SET_VERSION,
        help=f"Feature set: {FEATURE_SET_VERSION} (base) o {FEATURE_SET_VERSION_V2} (con xG).",
    ),
) -> None:
    divisions = big_five_division_codes()
    matches = _load_db_match_results(
        start_season=start_season,
        end_season=end_season,
        divisions=divisions,
    )
    payloads = _load_db_feature_payloads(
        feature_set_version=feature_set,
        start_season=start_season,
        end_season=end_season,
        divisions=divisions,
    )
    feature_keys = FEATURE_KEYS_V2 if feature_set == FEATURE_SET_VERSION_V2 else FEATURE_KEYS
    try:
        ml_metrics = run_configured_ml_walk_forward(
            matches,
            payloads,
            start_season=start_season,
            end_season=end_season,
            initial_train_seasons=initial_train_seasons,
            models=ml_models_for_keys(feature_keys),
        )
    except ValueError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc

    baseline_metrics = _run_walk_forward_or_exit(
        matches,
        start_season=start_season,
        end_season=end_season,
        initial_train_seasons=initial_train_seasons,
    )

    if not ml_metrics:
        typer.echo(
            "No hay features suficientes para el modelo logistico. "
            f"Corre build-rolling-features-db (feature_set_version={FEATURE_SET_VERSION}).",
            err=True,
        )
    combined = [*baseline_metrics, *ml_metrics]
    ml_windows = {
        (metric.division, metric.evaluation_season)
        for metric in ml_metrics
    }
    typer.echo(
        f"Walk-forward ML vs baselines {start_season}-{end_season} - "
        f"ml windows={len(ml_windows)}"
    )
    _echo_metric_csv(summarize_walk_forward_metrics(combined))


@app.command("club-elo-coverage-db")
def club_elo_coverage_db(
    start_season: str = typer.Option(
        DEFAULT_BIG_FIVE_START_SEASON,
        help="Temporada inicial, por ejemplo 1617.",
    ),
    end_season: str = typer.Option(
        DEFAULT_BIG_FIVE_END_SEASON,
        help="Temporada final, por ejemplo 2526.",
    ),
    cache_dir: Path = typer.Option(
        Path("data/raw/clubelo"),
        help="Carpeta de cache local para historiales Club Elo.",
    ),
    force: bool = typer.Option(False, help="Descargar aunque el historial ya exista en cache."),
    timeout: float = typer.Option(30.0, help="Timeout por solicitud a Club Elo, en segundos."),
    workers: int = typer.Option(6, help="Descargas paralelas maximas."),
    offline: bool = typer.Option(False, help="Usar solo cache local, sin descargar."),
) -> None:
    divisions = big_five_division_codes()
    matches = _load_db_match_results(
        start_season=start_season,
        end_season=end_season,
        divisions=divisions,
    )
    _load_club_elo_predictor_or_exit(
        matches,
        cache_dir=cache_dir,
        force=force,
        timeout=timeout,
        max_workers=workers,
        allow_download=not offline,
    )


@app.command("freeze-walk-forward-predictions-db")
def freeze_walk_forward_predictions_db(
    start_season: str = typer.Option(
        DEFAULT_BIG_FIVE_START_SEASON,
        help="Temporada inicial, por ejemplo 1617.",
    ),
    end_season: str = typer.Option(
        DEFAULT_BIG_FIVE_END_SEASON,
        help="Temporada final, por ejemplo 2526.",
    ),
    initial_train_seasons: int = typer.Option(
        DEFAULT_INITIAL_TRAIN_SEASONS,
        help="Cantidad de temporadas iniciales usadas como entrenamiento historico.",
    ),
    include_club_elo: bool = typer.Option(
        False,
        help="Incluir benchmark externo de Club Elo usando cache local.",
    ),
    club_elo_cache_dir: Path = typer.Option(
        Path("data/raw/clubelo"),
        help="Carpeta de cache local para historiales Club Elo.",
    ),
    club_elo_offline: bool = typer.Option(
        True,
        help="Usar solo cache local de Club Elo, sin descargar.",
    ),
    dry_run: bool = typer.Option(False, help="Preparar predicciones sin escribir en PostgreSQL."),
) -> None:
    divisions = big_five_division_codes()
    matches = _load_db_match_results(
        start_season=start_season,
        end_season=end_season,
        divisions=divisions,
    )
    extra_providers = None
    if include_club_elo:
        club_elo_predictor = _load_club_elo_predictor_or_exit(
            matches,
            cache_dir=club_elo_cache_dir,
            force=False,
            timeout=10.0,
            max_workers=6,
            allow_download=not club_elo_offline,
        )
        extra_providers = (club_elo_predictor,)
    predictions = _run_walk_forward_predictions_or_exit(
        matches,
        start_season=start_season,
        end_season=end_season,
        initial_train_seasons=initial_train_seasons,
        extra_prediction_providers=extra_providers,
    )
    _echo_walk_forward_prediction_batch(predictions)
    if dry_run:
        typer.echo("Dry run: no database writes executed.")
        return
    _persist_walk_forward_predictions(predictions)


@app.command("evaluate-predictions-db")
def evaluate_predictions_db(
    dry_run: bool = typer.Option(False, help="Calcular metricas sin escribir en PostgreSQL."),
) -> None:
    summary = _evaluate_predictions(commit=not dry_run)
    _echo_prediction_evaluation_summary(summary)
    if dry_run:
        typer.echo("Dry run: no database writes executed.")


@app.command("predictions-status")
def predictions_status() -> None:
    rows = _prediction_status_rows()
    typer.echo(
        "model,algorithm,feature_set_version,predictions,evaluated,"
        "avg_rps,avg_log_loss,avg_brier"
    )
    for row in rows:
        typer.echo(
            f"{row['model']},{row['algorithm']},{row['feature_set_version']},"
            f"{row['predictions']},{row['evaluated']},"
            f"{_optional_metric(row['avg_rps'])},"
            f"{_optional_metric(row['avg_log_loss'])},"
            f"{_optional_metric(row['avg_brier'])}"
        )


@app.command("build-calibration-bins-db")
def build_calibration_bins_db(
    bins: int = typer.Option(10, min=1, help="Cantidad de bins de calibracion."),
    dry_run: bool = typer.Option(False, help="Calcular curvas sin escribir en PostgreSQL."),
) -> None:
    calibration = _build_calibration_or_exit(n_bins=bins)
    _echo_calibration_build(calibration)
    if dry_run:
        typer.echo("Dry run: no database writes executed.")
        return
    _persist_calibration(calibration)


@app.command("calibration-status")
def calibration_status(
    bins: int = typer.Option(10, min=1, help="Cantidad de bins de calibracion."),
) -> None:
    rows = _calibration_status_rows(n_bins=bins)
    typer.echo(
        "model,algorithm,feature_set_version,model_versions,bins,class_samples,"
        "calibration_error"
    )
    for row in rows:
        typer.echo(
            f"{row['model']},{row['algorithm']},{row['feature_set_version']},"
            f"{row['model_versions']},{row['bins']},{row['class_samples']},"
            f"{_optional_metric(row['calibration_error'])}"
        )


@app.command("model-metrics-status")
def model_metrics_status() -> None:
    from futpredict.core.config import settings
    from futpredict.db.session import SessionLocal

    try:
        with SessionLocal() as session:
            rows = session.execute(
                text(
                    """
                    SELECT
                        model_versions.name AS model,
                        model_versions.algorithm,
                        model_versions.feature_set_version,
                        count(model_metrics.id) AS windows,
                        sum(model_metrics.n_matches) AS matches,
                        sum(model_metrics.rps * model_metrics.n_matches)
                            / sum(model_metrics.n_matches) AS weighted_rps,
                        sum(model_metrics.log_loss * model_metrics.n_matches)
                            / sum(model_metrics.n_matches) AS weighted_log_loss,
                        sum(model_metrics.brier * model_metrics.n_matches)
                            / sum(model_metrics.n_matches) AS weighted_brier,
                        sum(model_metrics.accuracy * model_metrics.n_matches)
                            / sum(model_metrics.n_matches) AS weighted_accuracy
                    FROM model_metrics
                    JOIN model_versions ON model_versions.id = model_metrics.model_version_id
                    GROUP BY
                        model_versions.name,
                        model_versions.algorithm,
                        model_versions.feature_set_version
                    ORDER BY weighted_rps
                    """
                )
            ).mappings().all()
    except SQLAlchemyError as exc:
        _echo_database_error(settings.database_url, exc)
        raise typer.Exit(1) from exc

    typer.echo(
        "model,algorithm,feature_set_version,windows,matches,"
        "weighted_rps,weighted_log_loss,weighted_brier,weighted_accuracy"
    )
    for row in rows:
        typer.echo(
            f"{row['model']},{row['algorithm']},{row['feature_set_version']},"
            f"{row['windows']},{row['matches']},{float(row['weighted_rps']):.6f},"
            f"{float(row['weighted_log_loss']):.6f},{float(row['weighted_brier']):.6f},"
            f"{float(row['weighted_accuracy']):.4f}"
        )


@app.command("sync-mlflow-model-versions")
def sync_mlflow_model_versions(
    tracking_uri: str | None = typer.Option(
        None,
        help="MLflow tracking URI. Si se omite, usa MLFLOW_TRACKING_URI.",
    ),
    experiment_name: str = typer.Option(
        DEFAULT_MLFLOW_EXPERIMENT_NAME,
        help="Nombre del experimento MLflow.",
    ),
    force: bool = typer.Option(
        False,
        help="Refrescar metricas de runs MLflow existentes aunque artifact_uri ya tenga valor.",
    ),
) -> None:
    from futpredict.core.config import settings
    from futpredict.db.session import SessionLocal

    uri = tracking_uri or settings.mlflow_tracking_uri
    try:
        with SessionLocal() as session:
            summary = sync_model_versions_to_mlflow(
                session,
                tracking_uri=uri,
                experiment_name=experiment_name,
                only_missing=not force,
            )
    except SQLAlchemyError as exc:
        _echo_database_error(settings.database_url, exc)
        raise typer.Exit(1) from exc
    except (httpx.HTTPError, ValueError) as exc:
        typer.echo(f"MLflow sync failed: {exc}", err=True)
        raise typer.Exit(1) from exc

    _echo_mlflow_sync_summary(summary)


@app.command("inspect-normalized-football-data-uk")
def inspect_normalized_football_data_uk(
    season: str = typer.Option(..., help="Codigo de temporada, por ejemplo 2526."),
    division: str = typer.Option(..., help="Codigo de liga, por ejemplo E0."),
    cache_dir: Path = typer.Option(
        Path("data/raw/football-data-uk"),
        help="Carpeta de cache local.",
    ),
) -> None:
    _echo_normalized_report(
        _normalized_football_data_uk_batch(season=season, division=division, cache_dir=cache_dir)
    )


@app.command("inspect-normalized-big-five")
def inspect_normalized_big_five(
    start_season: str = typer.Option(
        DEFAULT_BIG_FIVE_START_SEASON,
        help="Temporada inicial, por ejemplo 1617.",
    ),
    end_season: str = typer.Option(
        DEFAULT_BIG_FIVE_END_SEASON,
        help="Temporada final, por ejemplo 2526.",
    ),
    cache_dir: Path = typer.Option(
        Path("data/raw/football-data-uk"),
        help="Carpeta de cache local.",
    ),
) -> None:
    _echo_normalized_report(
        _normalized_big_five_batch(
            start_season=start_season,
            end_season=end_season,
            cache_dir=cache_dir,
        )
    )


@app.command("load-football-data-uk-db")
def load_football_data_uk_db(
    season: str = typer.Option(..., help="Codigo de temporada, por ejemplo 2526."),
    division: str = typer.Option(..., help="Codigo de liga, por ejemplo E0."),
    cache_dir: Path = typer.Option(
        Path("data/raw/football-data-uk"),
        help="Carpeta de cache local.",
    ),
    dry_run: bool = typer.Option(False, help="Validar staging sin escribir en PostgreSQL."),
) -> None:
    batch = _normalized_football_data_uk_batch(
        season=season,
        division=division,
        cache_dir=cache_dir,
    )
    _echo_normalized_report(batch)
    if dry_run:
        typer.echo("Dry run: no database writes executed.")
        return
    _persist_batch(batch)


@app.command("load-big-five-db")
def load_big_five_db(
    start_season: str = typer.Option(
        DEFAULT_BIG_FIVE_START_SEASON,
        help="Temporada inicial, por ejemplo 1617.",
    ),
    end_season: str = typer.Option(
        DEFAULT_BIG_FIVE_END_SEASON,
        help="Temporada final, por ejemplo 2526.",
    ),
    cache_dir: Path = typer.Option(
        Path("data/raw/football-data-uk"),
        help="Carpeta de cache local.",
    ),
    dry_run: bool = typer.Option(False, help="Validar staging sin escribir en PostgreSQL."),
) -> None:
    batch = _normalized_big_five_batch(
        start_season=start_season,
        end_season=end_season,
        cache_dir=cache_dir,
    )
    _echo_normalized_report(batch)
    if dry_run:
        typer.echo("Dry run: no database writes executed.")
        return
    _persist_batch(batch)


@app.command("load-football-data-uk-fixtures-db")
def load_football_data_uk_fixtures_db(
    season: str = typer.Option(
        current_season_code(),
        help="Codigo de temporada, por ejemplo 2627.",
    ),
    division: str = typer.Option(..., help="Codigo de liga, por ejemplo E0."),
    cache_dir: Path = typer.Option(
        Path("data/raw/football-data-uk"),
        help="Carpeta de cache local.",
    ),
    force: bool = typer.Option(True, help="Descargar el fixture semanal antes de cargar."),
    dry_run: bool = typer.Option(False, help="Validar staging sin escribir en PostgreSQL."),
) -> None:
    batch = _normalized_weekly_fixtures_batch(
        season=season,
        divisions=[division.upper()],
        cache_dir=cache_dir,
        force=force,
    )
    _echo_normalized_report(batch)
    if dry_run:
        typer.echo("Dry run: no database writes executed.")
        return
    _persist_batch(batch)


@app.command("load-big-five-fixtures-db")
def load_big_five_fixtures_db(
    season: str = typer.Option(
        current_season_code(),
        help="Codigo de temporada, por ejemplo 2627.",
    ),
    cache_dir: Path = typer.Option(
        Path("data/raw/football-data-uk"),
        help="Carpeta de cache local.",
    ),
    force: bool = typer.Option(True, help="Descargar el fixture semanal antes de cargar."),
    dry_run: bool = typer.Option(False, help="Validar staging sin escribir en PostgreSQL."),
) -> None:
    batch = _normalized_weekly_fixtures_batch(
        season=season,
        divisions=big_five_division_codes(),
        cache_dir=cache_dir,
        force=force,
    )
    _echo_normalized_report(batch)
    if dry_run:
        typer.echo("Dry run: no database writes executed.")
        return
    _persist_batch(batch)


@app.command("db-status")
def db_status() -> None:
    from futpredict.core.config import settings
    from futpredict.db.session import SessionLocal

    try:
        with SessionLocal() as session:
            session.execute(text("select 1"))
    except SQLAlchemyError as exc:
        _echo_database_error(settings.database_url, exc)
        raise typer.Exit(1) from exc

    typer.echo(f"Database OK: {_safe_database_url(settings.database_url)}")


@app.command("fixtures-status")
def fixtures_status() -> None:
    from futpredict.core.config import settings
    from futpredict.db.session import SessionLocal

    try:
        with SessionLocal() as session:
            rows = session.execute(
                text(
                    """
                    SELECT
                        leagues.code AS league,
                        count(DISTINCT matches.id) AS fixtures,
                        count(DISTINCT odds.id) AS odds,
                        min(matches.kickoff_utc) AS first_kickoff,
                        max(matches.kickoff_utc) AS last_kickoff
                    FROM matches
                    JOIN leagues ON leagues.id = matches.league_id
                    LEFT JOIN odds ON odds.match_id = matches.id
                    WHERE
                        matches.status <> 'finished'
                        OR matches.home_goals IS NULL
                        OR matches.away_goals IS NULL
                    GROUP BY leagues.code
                    ORDER BY leagues.code
                    """
                )
            ).mappings().all()
    except SQLAlchemyError as exc:
        _echo_database_error(settings.database_url, exc)
        raise typer.Exit(1) from exc

    typer.echo("league,fixtures,odds,first_kickoff,last_kickoff")
    for row in rows:
        typer.echo(
            f"{row['league']},{row['fixtures']},{row['odds']},"
            f"{row['first_kickoff']},{row['last_kickoff']}"
        )


@app.command("team-aliases-status")
def team_aliases_status() -> None:
    from futpredict.core.config import settings
    from futpredict.db.session import SessionLocal

    try:
        with SessionLocal() as session:
            rows = session.execute(
                text(
                    """
                    SELECT
                        source,
                        count(*) AS aliases,
                        count(DISTINCT team_id) AS teams
                    FROM team_aliases
                    GROUP BY source
                    ORDER BY source
                    """
                )
            ).mappings().all()
    except SQLAlchemyError as exc:
        _echo_database_error(settings.database_url, exc)
        raise typer.Exit(1) from exc

    typer.echo("source,aliases,teams")
    for row in rows:
        typer.echo(f"{row['source']},{row['aliases']},{row['teams']}")


@app.command("build-rolling-features-db")
def build_rolling_features_db(
    start_season: str = typer.Option(
        DEFAULT_BIG_FIVE_START_SEASON,
        help="Temporada inicial, por ejemplo 1617.",
    ),
    end_season: str = typer.Option(
        DEFAULT_BIG_FIVE_END_SEASON,
        help="Temporada final, por ejemplo 2526.",
    ),
    with_xg: bool = typer.Option(
        False,
        help="Incluir features de xG (feature set rolling_v2). Requiere xG cargado.",
    ),
    dry_run: bool = typer.Option(False, help="Calcular features sin escribir en PostgreSQL."),
) -> None:
    divisions = big_five_division_codes()
    feature_matches = _load_db_feature_matches(
        start_season=start_season,
        end_season=end_season,
        divisions=divisions,
    )
    feature_set_version = FEATURE_SET_VERSION_V2 if with_xg else FEATURE_SET_VERSION
    snapshots = build_rolling_feature_snapshots(
        feature_matches,
        feature_set_version=feature_set_version,
        include_xg=with_xg,
    )
    _echo_feature_batch(
        feature_set_version=feature_set_version,
        matches=len(feature_matches),
        snapshots=len(snapshots),
    )
    if dry_run:
        typer.echo("Dry run: no database writes executed.")
        return
    _persist_feature_snapshots(snapshots)


@app.command("features-status")
def features_status() -> None:
    from futpredict.core.config import settings
    from futpredict.db.session import SessionLocal

    try:
        with SessionLocal() as session:
            rows = session.execute(
                text(
                    """
                    SELECT
                        feature_set_version,
                        count(*) AS features,
                        min(cutoff_utc) AS first_cutoff,
                        max(cutoff_utc) AS last_cutoff
                    FROM features
                    GROUP BY feature_set_version
                    ORDER BY feature_set_version
                    """
                )
            ).mappings().all()
    except SQLAlchemyError as exc:
        _echo_database_error(settings.database_url, exc)
        raise typer.Exit(1) from exc

    typer.echo("feature_set_version,features,first_cutoff,last_cutoff")
    for row in rows:
        typer.echo(
            f"{row['feature_set_version']},{row['features']},"
            f"{row['first_cutoff']},{row['last_cutoff']}"
        )


@app.command("build-elo-ratings-db")
def build_elo_ratings_db(
    start_season: str = typer.Option(
        DEFAULT_BIG_FIVE_START_SEASON,
        help="Temporada inicial, por ejemplo 1617.",
    ),
    end_season: str = typer.Option(
        DEFAULT_BIG_FIVE_END_SEASON,
        help="Temporada final, por ejemplo 2526.",
    ),
    dry_run: bool = typer.Option(False, help="Calcular Elo sin escribir en PostgreSQL."),
) -> None:
    divisions = big_five_division_codes()
    elo_matches = _load_db_elo_matches(
        start_season=start_season,
        end_season=end_season,
        divisions=divisions,
    )
    snapshots = build_elo_rating_snapshots(elo_matches)
    _echo_elo_batch(
        rating_system=ELO_RATING_SYSTEM,
        matches=len(elo_matches),
        ratings=len(snapshots),
    )
    if dry_run:
        typer.echo("Dry run: no database writes executed.")
        return
    _persist_elo_rating_snapshots(snapshots)


@app.command("elo-ratings-status")
def elo_ratings_status() -> None:
    from futpredict.core.config import settings
    from futpredict.db.session import SessionLocal

    try:
        with SessionLocal() as session:
            rows = session.execute(
                text(
                    """
                    SELECT
                        leagues.code AS league,
                        count(*) AS ratings,
                        count(DISTINCT elo_ratings.match_id) AS matches,
                        min(matches.kickoff_utc) AS first_match,
                        max(matches.kickoff_utc) AS last_match
                    FROM elo_ratings
                    JOIN matches ON matches.id = elo_ratings.match_id
                    JOIN leagues ON leagues.id = matches.league_id
                    GROUP BY leagues.code
                    ORDER BY leagues.code
                    """
                )
            ).mappings().all()
    except SQLAlchemyError as exc:
        _echo_database_error(settings.database_url, exc)
        raise typer.Exit(1) from exc

    typer.echo("league,ratings,matches,first_match,last_match")
    for row in rows:
        typer.echo(
            f"{row['league']},{row['ratings']},{row['matches']},"
            f"{row['first_match']},{row['last_match']}"
        )


@app.command("promote-champion")
def promote_champion(
    min_matches: int = typer.Option(
        100,
        min=1,
        help="Minimo de partidos agregados para considerar un modelo en el ranking.",
    ),
    dry_run: bool = typer.Option(
        False,
        help="Calcular el campeon sin escribir is_champion en PostgreSQL.",
    ),
) -> None:
    from futpredict.core.config import settings
    from futpredict.db.session import SessionLocal

    try:
        with SessionLocal() as session:
            summary = promote_champion_by_rps(
                session,
                min_matches=min_matches,
                commit=not dry_run,
            )
    except SQLAlchemyError as exc:
        _echo_database_error(settings.database_url, exc)
        raise typer.Exit(1) from exc
    _echo_champion_promotion_summary(summary)
    if dry_run:
        typer.echo("Dry run: no database writes executed.")


@app.command("champion-status")
def champion_status() -> None:
    from futpredict.core.config import settings
    from futpredict.db.session import SessionLocal

    try:
        with SessionLocal() as session:
            rows = champion_status_rows(session)
    except SQLAlchemyError as exc:
        _echo_database_error(settings.database_url, exc)
        raise typer.Exit(1) from exc

    typer.echo(
        "model,algorithm,feature_set_version,champion_versions,leagues,last_train_window_end"
    )
    for row in rows:
        typer.echo(
            f"{row['model']},{row['algorithm']},{row['feature_set_version']},"
            f"{row['champion_versions']},{row['leagues']},{row['last_train_window_end']}"
        )
    if not rows:
        typer.echo("champion=none")


@app.command("freeze-future-predictions-db")
def freeze_future_predictions_db(
    days: int = typer.Option(14, min=1, help="Ventana de dias hacia adelante para fixtures."),
    limit: int = typer.Option(200, min=1, help="Maximo de fixtures a considerar."),
    divisions: str | None = typer.Option(
        None,
        help="Lista de divisiones separadas por coma, por ejemplo E0,SP1.",
    ),
    dry_run: bool = typer.Option(False, help="Preparar predicciones sin escribir en PostgreSQL."),
) -> None:
    from futpredict.core.config import settings
    from futpredict.db.session import SessionLocal

    division_codes = _division_codes_option(divisions)
    try:
        with SessionLocal() as session:
            summary = freeze_future_predictions(
                session,
                days=days,
                limit=limit,
                division_codes=division_codes,
                commit=not dry_run,
            )
    except SQLAlchemyError as exc:
        _echo_database_error(settings.database_url, exc)
        raise typer.Exit(1) from exc
    except ValueError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc
    _echo_future_freeze_summary(summary)
    if dry_run:
        typer.echo("Dry run: no database writes executed.")


@app.command("run-weekly")
def run_weekly(
    start_season: str = typer.Option(
        DEFAULT_BIG_FIVE_START_SEASON,
        help="Temporada inicial, por ejemplo 1617.",
    ),
    end_season: str = typer.Option(
        DEFAULT_BIG_FIVE_END_SEASON,
        help="Temporada final, por ejemplo 2526.",
    ),
    initial_train_seasons: int = typer.Option(
        DEFAULT_INITIAL_TRAIN_SEASONS,
        help="Temporadas iniciales usadas como entrenamiento historico.",
    ),
    future_days: int = typer.Option(14, min=1, help="Ventana de dias para predicciones futuras."),
    future_limit: int = typer.Option(200, min=1, help="Maximo de fixtures futuros a congelar."),
    champion_min_matches: int = typer.Option(
        100,
        min=1,
        help="Minimo de partidos agregados para promover campeon.",
    ),
    include_ingest: bool = typer.Option(
        True,
        help="Descargar resultados y fixtures frescos antes de recalcular (best-effort).",
    ),
    include_future: bool = typer.Option(
        True,
        help="Incluir el paso de congelar predicciones futuras.",
    ),
    dry_run: bool = typer.Option(False, help="Ejecutar el pipeline sin escribir en PostgreSQL."),
) -> None:
    from futpredict.core.config import settings
    from futpredict.db.session import SessionLocal

    config = WeeklyPipelineConfig(
        start_season=start_season,
        end_season=end_season,
        initial_train_seasons=initial_train_seasons,
        future_days=future_days,
        future_limit=future_limit,
        champion_min_matches=champion_min_matches,
        include_ingest=include_ingest,
        include_future=include_future,
    )
    try:
        with SessionLocal() as session:
            results = run_weekly_pipeline(
                session,
                config=config,
                dry_run=dry_run,
                logger=typer.echo,
            )
    except WeeklyPipelineError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc
    except SQLAlchemyError as exc:
        _echo_database_error(settings.database_url, exc)
        raise typer.Exit(1) from exc

    typer.echo("step,status,detail")
    for result in results:
        typer.echo(f"{result.name},{result.status},{result.detail}")


def _normalized_football_data_uk_batch(
    season: str,
    division: str,
    cache_dir: Path,
) -> NormalizedBatch:
    csv_path = download_csv(season=season, division=division, cache_dir=cache_dir)
    frame = read_csv_file(csv_path, season=season, division=division)
    matches = parse_matches(frame, season=season, division=division)
    return build_normalized_batch(matches)


def _normalized_big_five_batch(
    start_season: str,
    end_season: str,
    cache_dir: Path,
) -> NormalizedBatch:
    seasons = season_range(start_season, end_season)
    divisions = big_five_division_codes()
    matches = load_matches(seasons=seasons, divisions=divisions, cache_dir=cache_dir)
    return build_normalized_batch(matches)


def _normalized_weekly_fixtures_batch(
    season: str,
    divisions: list[str],
    cache_dir: Path,
    force: bool,
) -> NormalizedBatch:
    fixtures = load_weekly_fixtures(
        season=season,
        divisions=divisions,
        cache_dir=cache_dir,
        force=force,
    )
    return build_normalized_fixture_batch(fixtures)


def _echo_normalized_report(batch: NormalizedBatch) -> None:
    validation = validate_normalized_batch(batch)
    summary = summarize_normalized_batch(batch, validation)
    typer.echo("Normalized staging batch")
    typer.echo(f"leagues={summary.leagues}")
    typer.echo(f"seasons={summary.seasons}")
    typer.echo(f"teams={summary.teams}")
    typer.echo(f"team_aliases={summary.team_aliases}")
    typer.echo(f"matches={summary.matches}")
    typer.echo(f"odds={summary.odds}")
    typer.echo(f"missing_odds={summary.missing_odds}")
    typer.echo(f"duplicate_matches={summary.duplicate_matches}")
    typer.echo(f"duplicate_odds={summary.duplicate_odds}")
    typer.echo(f"errors={'yes' if validation.has_errors else 'no'}")


def _persist_batch(batch: NormalizedBatch) -> None:
    from futpredict.core.config import settings
    from futpredict.db.session import SessionLocal

    try:
        with SessionLocal() as session:
            summary = load_normalized_batch(session, batch)
    except SQLAlchemyError as exc:
        _echo_database_error(settings.database_url, exc)
        raise typer.Exit(1) from exc
    _echo_persistence_summary(summary)


def _load_db_match_results(
    *,
    start_season: str,
    end_season: str,
    divisions: list[str],
) -> list[MatchResult]:
    from futpredict.core.config import settings
    from futpredict.db.session import SessionLocal

    try:
        with SessionLocal() as session:
            return load_match_results_from_db(
                session,
                start_season=start_season,
                end_season=end_season,
                division_codes=divisions,
            )
    except SQLAlchemyError as exc:
        _echo_database_error(settings.database_url, exc)
        raise typer.Exit(1) from exc
    except ValueError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc


def _store_understat_xg_or_exit(
    understat_matches: list[UnderstatMatchXg],
    matches: list[MatchResult],
) -> UnderstatStoreSummary:
    from futpredict.core.config import settings
    from futpredict.db.session import SessionLocal

    try:
        with SessionLocal() as session:
            return store_understat_xg(session, understat_matches, matches)
    except SQLAlchemyError as exc:
        _echo_database_error(settings.database_url, exc)
        raise typer.Exit(1) from exc


def _load_db_feature_payloads(
    *,
    feature_set_version: str,
    start_season: str,
    end_season: str,
    divisions: list[str],
) -> dict[int, dict[str, float | int | None]]:
    from futpredict.core.config import settings
    from futpredict.db.session import SessionLocal

    try:
        with SessionLocal() as session:
            return load_feature_payloads_from_db(
                session,
                feature_set_version=feature_set_version,
                start_season=start_season,
                end_season=end_season,
                division_codes=divisions,
            )
    except SQLAlchemyError as exc:
        _echo_database_error(settings.database_url, exc)
        raise typer.Exit(1) from exc
    except ValueError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc


def _load_db_feature_matches(
    *,
    start_season: str,
    end_season: str,
    divisions: list[str],
) -> list[FeatureMatch]:
    from futpredict.core.config import settings
    from futpredict.db.session import SessionLocal

    try:
        with SessionLocal() as session:
            return load_feature_matches_from_db(
                session,
                start_season=start_season,
                end_season=end_season,
                division_codes=divisions,
            )
    except SQLAlchemyError as exc:
        _echo_database_error(settings.database_url, exc)
        raise typer.Exit(1) from exc
    except ValueError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc


def _load_db_elo_matches(
    *,
    start_season: str,
    end_season: str,
    divisions: list[str],
) -> list[EloMatch]:
    from futpredict.core.config import settings
    from futpredict.db.session import SessionLocal

    try:
        with SessionLocal() as session:
            return load_elo_matches_from_db(
                session,
                start_season=start_season,
                end_season=end_season,
                division_codes=divisions,
            )
    except SQLAlchemyError as exc:
        _echo_database_error(settings.database_url, exc)
        raise typer.Exit(1) from exc
    except ValueError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc


def _persist_feature_snapshots(snapshots: list[FeatureSnapshot]) -> None:
    from futpredict.core.config import settings
    from futpredict.db.session import SessionLocal

    try:
        with SessionLocal() as session:
            summary = upsert_feature_snapshots(session, snapshots)
    except SQLAlchemyError as exc:
        _echo_database_error(settings.database_url, exc)
        raise typer.Exit(1) from exc
    _echo_feature_persistence_summary(summary)


def _persist_elo_rating_snapshots(snapshots: list[EloRatingSnapshot]) -> None:
    from futpredict.core.config import settings
    from futpredict.db.session import SessionLocal

    try:
        with SessionLocal() as session:
            summary = upsert_elo_rating_snapshots(session, snapshots)
    except SQLAlchemyError as exc:
        _echo_database_error(settings.database_url, exc)
        raise typer.Exit(1) from exc
    _echo_elo_persistence_summary(summary)


def _run_walk_forward_or_exit(
    matches: list[MatchResult],
    *,
    start_season: str,
    end_season: str,
    initial_train_seasons: int,
    extra_prediction_providers: tuple[PredictionProvider, ...] | None = None,
) -> list[WalkForwardMetric]:
    try:
        return run_expanding_walk_forward(
            matches,
            start_season=start_season,
            end_season=end_season,
            initial_train_seasons=initial_train_seasons,
            extra_prediction_providers=extra_prediction_providers,
        )
    except ValueError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc


def _run_ml_walk_forward_or_exit(
    matches: list[MatchResult],
    *,
    start_season: str,
    end_season: str,
    initial_train_seasons: int,
) -> list[WalkForwardMetric]:
    payloads = _load_db_feature_payloads(
        feature_set_version=FEATURE_SET_VERSION,
        start_season=start_season,
        end_season=end_season,
        divisions=big_five_division_codes(),
    )
    try:
        return run_configured_ml_walk_forward(
            matches,
            payloads,
            start_season=start_season,
            end_season=end_season,
            initial_train_seasons=initial_train_seasons,
        )
    except ValueError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc


def _run_walk_forward_predictions_or_exit(
    matches: list[MatchResult],
    *,
    start_season: str,
    end_season: str,
    initial_train_seasons: int,
    extra_prediction_providers: tuple[PredictionProvider, ...] | None = None,
) -> list[WalkForwardPrediction]:
    try:
        return run_expanding_walk_forward_predictions(
            matches,
            start_season=start_season,
            end_season=end_season,
            initial_train_seasons=initial_train_seasons,
            extra_prediction_providers=extra_prediction_providers,
        )
    except ValueError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc


def _load_club_elo_predictor_or_exit(
    matches: list[MatchResult],
    *,
    cache_dir: Path,
    force: bool,
    timeout: float,
    max_workers: int,
    allow_download: bool,
) -> ClubEloPredictor:
    try:
        predictor, history_load = load_club_elo_predictor_for_matches(
            matches,
            cache_dir=cache_dir,
            force=force,
            timeout=timeout,
            max_workers=max_workers,
            allow_download=allow_download,
            progress_callback=_echo_club_elo_history_progress,
        )
    except httpx.HTTPError as exc:
        typer.echo(f"Club Elo download failed: {exc.__class__.__name__}", err=True)
        raise typer.Exit(1) from exc

    coverage = predictor.coverage_for_matches(matches)
    _echo_club_elo_status(
        loaded_teams=history_load.loaded_teams,
        missing_teams=history_load.missing_teams,
        coverage=coverage,
    )
    return predictor


def _persist_walk_forward_predictions(predictions: list[WalkForwardPrediction]) -> None:
    from futpredict.core.config import settings
    from futpredict.db.session import SessionLocal

    try:
        with SessionLocal() as session:
            summary = freeze_walk_forward_predictions(session, predictions)
    except SQLAlchemyError as exc:
        _echo_database_error(settings.database_url, exc)
        raise typer.Exit(1) from exc
    except ValueError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc
    _echo_prediction_persistence_summary(summary)


def _evaluate_predictions(*, commit: bool) -> PredictionEvaluationSummary:
    from futpredict.core.config import settings
    from futpredict.db.session import SessionLocal

    try:
        with SessionLocal() as session:
            return evaluate_pending_predictions(session, commit=commit)
    except SQLAlchemyError as exc:
        _echo_database_error(settings.database_url, exc)
        raise typer.Exit(1) from exc
    except ValueError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc


def _prediction_status_rows() -> list[dict[str, object]]:
    from futpredict.core.config import settings
    from futpredict.db.session import SessionLocal

    try:
        with SessionLocal() as session:
            return prediction_status_rows(session)
    except SQLAlchemyError as exc:
        _echo_database_error(settings.database_url, exc)
        raise typer.Exit(1) from exc


def _build_calibration_or_exit(*, n_bins: int) -> CalibrationBuild:
    from futpredict.core.config import settings
    from futpredict.db.session import SessionLocal

    try:
        with SessionLocal() as session:
            return build_calibration_from_predictions(session, n_bins=n_bins)
    except SQLAlchemyError as exc:
        _echo_database_error(settings.database_url, exc)
        raise typer.Exit(1) from exc
    except ValueError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc


def _persist_calibration(calibration: CalibrationBuild) -> None:
    from futpredict.core.config import settings
    from futpredict.db.session import SessionLocal

    try:
        with SessionLocal() as session:
            summary = upsert_calibration_bins(session, calibration)
    except SQLAlchemyError as exc:
        _echo_database_error(settings.database_url, exc)
        raise typer.Exit(1) from exc
    except ValueError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc
    _echo_calibration_persistence_summary(summary)


def _calibration_status_rows(*, n_bins: int) -> list[dict[str, object]]:
    from futpredict.core.config import settings
    from futpredict.db.session import SessionLocal

    try:
        with SessionLocal() as session:
            return calibration_status_rows(session, n_bins=n_bins)
    except SQLAlchemyError as exc:
        _echo_database_error(settings.database_url, exc)
        raise typer.Exit(1) from exc


def _echo_club_elo_history_progress(
    done: int,
    total: int,
    team_name: str,
    loaded: bool,
) -> None:
    status = "ok" if loaded else "missing"
    typer.echo(f"club_elo_history,{done},{total},{status},{team_name}")


def _persist_walk_forward_metrics(metrics: list[WalkForwardMetric]) -> None:
    from futpredict.core.config import settings
    from futpredict.db.session import SessionLocal

    try:
        with SessionLocal() as session:
            summary = upsert_walk_forward_metrics(session, metrics)
    except SQLAlchemyError as exc:
        _echo_database_error(settings.database_url, exc)
        raise typer.Exit(1) from exc
    except ValueError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc
    _echo_walk_forward_persistence_summary(summary)


def _backtest_summaries_or_exit(matches: list[MatchResult]) -> list[MetricSummary]:
    try:
        return backtest_summary(matches)
    except ValueError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc


def _echo_metric_csv(summaries: list[MetricSummary]) -> None:
    typer.echo("model,n_matches,rps,log_loss,brier,accuracy")
    for summary in summaries:
        typer.echo(
            f"{summary.model},{summary.n_matches},{summary.rps:.6f},"
            f"{summary.log_loss:.6f},{summary.brier:.6f},{summary.accuracy:.4f}"
        )


def _echo_feature_batch(feature_set_version: str, matches: int, snapshots: int) -> None:
    typer.echo("Feature batch")
    typer.echo(f"feature_set_version={feature_set_version}")
    typer.echo(f"matches={matches}")
    typer.echo(f"snapshots={snapshots}")


def _echo_feature_persistence_summary(summary: FeaturePersistenceSummary) -> None:
    typer.echo("Persisted feature batch")
    typer.echo(f"feature_set_version={summary.feature_set_version}")
    typer.echo(f"features={summary.features}")


def _echo_elo_batch(rating_system: str, matches: int, ratings: int) -> None:
    typer.echo("Elo rating batch")
    typer.echo(f"rating_system={rating_system}")
    typer.echo(f"matches={matches}")
    typer.echo(f"ratings={ratings}")


def _echo_elo_persistence_summary(summary: EloPersistenceSummary) -> None:
    typer.echo("Persisted Elo rating batch")
    typer.echo(f"rating_system={summary.rating_system}")
    typer.echo(f"matches={summary.matches}")
    typer.echo(f"ratings={summary.ratings}")


def _echo_walk_forward_summary(metrics: list[WalkForwardMetric]) -> None:
    windows = {
        (
            metric.division,
            metric.evaluation_season,
            metric.train_start_season,
            metric.train_end_season,
        )
        for metric in metrics
    }
    typer.echo("Walk-forward baseline summary")
    typer.echo(f"windows={len(windows)}")
    typer.echo(f"metrics={len(metrics)}")
    _echo_metric_csv(summarize_walk_forward_metrics(metrics))


def _echo_walk_forward_persistence_summary(summary: WalkForwardPersistenceSummary) -> None:
    typer.echo("Persisted walk-forward metrics")
    typer.echo(f"model_versions={summary.model_versions}")
    typer.echo(f"metrics={summary.metrics}")


def _echo_mlflow_sync_summary(summary: MlflowSyncSummary) -> None:
    typer.echo("Synced model versions to MLflow")
    typer.echo(f"experiment_id={summary.experiment_id}")
    typer.echo(f"scanned_model_versions={summary.scanned_model_versions}")
    typer.echo(f"skipped_model_versions={summary.skipped_model_versions}")
    typer.echo(f"reused_runs={summary.reused_runs}")
    typer.echo(f"created_runs={summary.created_runs}")
    typer.echo(f"logged_runs={summary.logged_runs}")
    typer.echo(f"updated_model_versions={summary.updated_model_versions}")


def _echo_walk_forward_prediction_batch(predictions: list[WalkForwardPrediction]) -> None:
    windows = {
        (
            prediction.division,
            prediction.evaluation_season,
            prediction.train_start_season,
            prediction.train_end_season,
        )
        for prediction in predictions
    }
    counts_by_model: dict[str, int] = {}
    for prediction in predictions:
        counts_by_model[prediction.prediction.model] = (
            counts_by_model.get(prediction.prediction.model, 0) + 1
        )

    typer.echo("Walk-forward prediction batch")
    typer.echo(f"windows={len(windows)}")
    typer.echo(f"predictions={len(predictions)}")
    typer.echo("model,predictions")
    for model, count in sorted(counts_by_model.items()):
        typer.echo(f"{model},{count}")


def _echo_prediction_persistence_summary(summary: PredictionPersistenceSummary) -> None:
    typer.echo("Persisted immutable predictions")
    typer.echo(f"model_versions={summary.model_versions}")
    typer.echo(f"candidates={summary.candidates}")
    typer.echo(f"inserted_predictions={summary.inserted_predictions}")
    typer.echo(f"existing_predictions={summary.existing_predictions}")


def _echo_prediction_evaluation_summary(summary: PredictionEvaluationSummary) -> None:
    typer.echo("Evaluated predictions")
    typer.echo(f"evaluated_predictions={summary.evaluated_predictions}")


def _echo_calibration_build(calibration: CalibrationBuild) -> None:
    typer.echo("Calibration bin batch")
    typer.echo(f"n_bins={calibration.bins[0].n_bins if calibration.bins else 0}")
    typer.echo(
        f"model_versions={len({bin_summary.model_version_id for bin_summary in calibration.bins})}"
    )
    typer.echo(f"bins={len(calibration.bins)}")
    typer.echo(f"class_samples={calibration.class_samples}")


def _echo_calibration_persistence_summary(summary: CalibrationPersistenceSummary) -> None:
    typer.echo("Persisted calibration bins")
    typer.echo(f"n_bins={summary.n_bins}")
    typer.echo(f"model_versions={summary.model_versions}")
    typer.echo(f"bins={summary.bins}")
    typer.echo(f"class_samples={summary.class_samples}")


def _echo_club_elo_status(
    *,
    loaded_teams: int,
    missing_teams: int,
    coverage: ClubEloPredictionCoverage,
) -> None:
    typer.echo("Club Elo coverage")
    typer.echo(f"loaded_teams={loaded_teams}")
    typer.echo(f"missing_teams={missing_teams}")
    typer.echo(f"matches={coverage.total_matches}")
    typer.echo(f"predicted_matches={coverage.predicted_matches}")
    typer.echo(f"skipped_matches={coverage.skipped_matches}")
    typer.echo(f"coverage={coverage.coverage_ratio:.4f}")
    if coverage.missing_team_names:
        typer.echo("missing_team_names=" + ",".join(coverage.missing_team_names))


def _echo_persistence_summary(summary: PersistenceSummary) -> None:
    typer.echo("Persisted staging batch")
    typer.echo(f"leagues={summary.leagues}")
    typer.echo(f"seasons={summary.seasons}")
    typer.echo(f"teams={summary.teams}")
    typer.echo(f"team_aliases={summary.team_aliases}")
    typer.echo(f"matches={summary.matches}")
    typer.echo(f"odds={summary.odds}")


def _echo_champion_promotion_summary(summary: ChampionPromotionSummary) -> None:
    typer.echo("Champion promotion")
    typer.echo(f"champion_model={summary.champion_model or 'none'}")
    typer.echo(f"algorithm={summary.algorithm or ''}")
    typer.echo(f"feature_set_version={summary.feature_set_version or ''}")
    typer.echo(f"weighted_rps={_optional_metric(summary.weighted_rps)}")
    typer.echo(f"matches={summary.matches}")
    typer.echo(f"windows={summary.windows}")
    typer.echo(f"promoted_versions={summary.promoted_versions}")
    typer.echo(f"demoted_versions={summary.demoted_versions}")
    typer.echo(f"champion_versions={summary.champion_versions}")


def _echo_future_freeze_summary(summary: FuturePredictionFreezeSummary) -> None:
    typer.echo("Future prediction freeze")
    typer.echo(f"frozen_at={summary.frozen_at.isoformat()}")
    typer.echo(f"fixtures={summary.fixtures}")
    typer.echo(f"eligible_fixtures={summary.eligible_fixtures}")
    typer.echo(f"model_versions={summary.model_versions}")
    typer.echo(f"candidates={summary.candidates}")
    typer.echo(f"inserted_predictions={summary.inserted_predictions}")
    typer.echo(f"existing_predictions={summary.existing_predictions}")
    typer.echo(f"skipped_without_window={summary.skipped_without_window}")


def _division_codes_option(value: str | None) -> list[str] | None:
    if value is None:
        return None
    divisions = [item.strip().upper() for item in value.split(",") if item.strip()]
    return divisions or None


def _echo_database_error(database_url: str, exc: SQLAlchemyError) -> None:
    typer.echo(f"Database connection failed: {_safe_database_url(database_url)}", err=True)
    typer.echo(f"Reason: {exc.__class__.__name__}", err=True)
    typer.echo(
        "Revisa que PostgreSQL este levantado y que DATABASE_URL tenga usuario, clave, host y "
        "base correctos.",
        err=True,
    )


def _safe_database_url(database_url: str) -> str:
    if "://" not in database_url or "@" not in database_url:
        return database_url
    scheme, rest = database_url.split("://", maxsplit=1)
    credentials, location = rest.split("@", maxsplit=1)
    if ":" not in credentials:
        return f"{scheme}://{credentials}@{location}"
    user, _password = credentials.split(":", maxsplit=1)
    return f"{scheme}://{user}:***@{location}"


def _optional_metric(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, Decimal | int | float):
        return f"{float(value):.6f}"
    return str(value)


if __name__ == "__main__":
    app()

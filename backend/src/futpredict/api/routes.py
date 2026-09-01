from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import cast

import httpx
from fastapi import APIRouter, HTTPException, Query
from sqlalchemy.exc import SQLAlchemyError

from futpredict.api.schemas import (
    BacktestBreakdownResponse,
    BacktestMetricResponse,
    BacktestResponse,
    CalibrationCurvePointResponse,
    CalibrationCurveResponse,
    CalibrationStatusResponse,
    CalibrationStatusRowResponse,
    FixtureModelPredictionResponse,
    FixturePredictionRowResponse,
    FixturePredictionsResponse,
    FixtureResponse,
    HealthResponse,
    MatchDetailHeadToHeadResponse,
    MatchDetailResponse,
    ModelRankingResponse,
    ModelRankingRowResponse,
    PredictionHistoryResponse,
    PredictionHistoryRowResponse,
    PredictionHistorySummaryResponse,
    PredictionStatusResponse,
    PredictionStatusRowResponse,
    UpcomingFixturesResponse,
)
from futpredict.core.config import settings
from futpredict.data.db_fixtures import load_upcoming_fixtures_from_db
from futpredict.data.db_match_detail import load_match_detail
from futpredict.data.db_matches import (
    load_finished_match_results_before_from_db,
    load_match_results_from_db,
)
from futpredict.data.football_data_uk_catalog import (
    DEFAULT_BIG_FIVE_END_SEASON,
    DEFAULT_BIG_FIVE_START_SEASON,
    big_five_division_codes,
    season_range,
)
from futpredict.domain.fixtures import Fixture
from futpredict.domain.matches import MatchResult
from futpredict.evaluation.backtest import (
    MetricSummary,
    run_baseline_backtest,
    summarize_prediction_breakdowns,
    summarize_predictions,
)
from futpredict.evaluation.db_calibration import (
    calibration_curve_rows,
    calibration_status_rows,
)
from futpredict.evaluation.db_history import (
    prediction_history_rows,
    prediction_history_summary,
)
from futpredict.evaluation.db_models import champion_model_row, model_ranking_rows
from futpredict.evaluation.db_predictions import prediction_status_rows
from futpredict.evaluation.future_predictions import (
    SUPPORTED_FUTURE_MODELS,
    FixturePrediction,
    build_fixture_predictions,
)
from futpredict.ingest.providers.football_data_uk import load_matches

router = APIRouter()
DB_BACKTEST_SOURCE = "postgresql:football-data.co.uk"


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(status="ok", app_env=settings.app_env)


@router.get("/backtests/football-data-uk", response_model=BacktestResponse)
def football_data_uk_backtest(
    season: str = Query("2526", pattern=r"^\d{4}$"),
    division: str = Query("E0", min_length=2, max_length=4),
) -> BacktestResponse:
    matches = _load_football_data_uk_matches(
        seasons=[season],
        divisions=[division.upper()],
    )
    return _backtest_response(
        scope="single_division",
        source="football-data.co.uk",
        start_season=season,
        end_season=season,
        divisions=[division.upper()],
        matches=matches,
    )


@router.get("/backtests/football-data-uk/big-five", response_model=BacktestResponse)
def football_data_uk_big_five_backtest(
    start_season: str = Query(DEFAULT_BIG_FIVE_START_SEASON, pattern=r"^\d{4}$"),
    end_season: str = Query(DEFAULT_BIG_FIVE_END_SEASON, pattern=r"^\d{4}$"),
) -> BacktestResponse:
    seasons = season_range(start_season, end_season)
    divisions = big_five_division_codes()
    matches = _load_football_data_uk_matches(seasons=seasons, divisions=divisions)
    return _backtest_response(
        scope="big_five",
        source="football-data.co.uk",
        start_season=start_season,
        end_season=end_season,
        divisions=divisions,
        matches=matches,
    )


@router.get("/backtests/db/football-data-uk", response_model=BacktestResponse)
def db_football_data_uk_backtest(
    season: str = Query("2526", pattern=r"^\d{4}$"),
    division: str = Query("E0", min_length=2, max_length=4),
) -> BacktestResponse:
    division_code = division.upper()
    matches = _load_db_matches(
        start_season=season,
        end_season=season,
        divisions=[division_code],
    )
    return _backtest_response(
        scope="single_division",
        source=DB_BACKTEST_SOURCE,
        start_season=season,
        end_season=season,
        divisions=[division_code],
        matches=matches,
    )


@router.get("/backtests/db/big-five", response_model=BacktestResponse)
def db_big_five_backtest(
    start_season: str = Query(DEFAULT_BIG_FIVE_START_SEASON, pattern=r"^\d{4}$"),
    end_season: str = Query(DEFAULT_BIG_FIVE_END_SEASON, pattern=r"^\d{4}$"),
) -> BacktestResponse:
    divisions = big_five_division_codes()
    matches = _load_db_matches(
        start_season=start_season,
        end_season=end_season,
        divisions=divisions,
    )
    return _backtest_response(
        scope="big_five",
        source=DB_BACKTEST_SOURCE,
        start_season=start_season,
        end_season=end_season,
        divisions=divisions,
        matches=matches,
    )


@router.get("/predictions/status", response_model=PredictionStatusResponse)
def prediction_status() -> PredictionStatusResponse:
    from futpredict.db.session import SessionLocal

    try:
        with SessionLocal() as session:
            rows = prediction_status_rows(session)
    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=503,
            detail=f"database unavailable: {exc.__class__.__name__}",
        ) from exc

    return PredictionStatusResponse(
        rows=[
            PredictionStatusRowResponse(
                model=str(row["model"]),
                algorithm=str(row["algorithm"]),
                feature_set_version=str(row["feature_set_version"]),
                predictions=_required_int(row["predictions"]),
                evaluated=_required_int(row["evaluated"]),
                avg_rps=_optional_float(row["avg_rps"]),
                avg_log_loss=_optional_float(row["avg_log_loss"]),
                avg_brier=_optional_float(row["avg_brier"]),
            )
            for row in rows
        ]
    )


@router.get("/predictions/history", response_model=PredictionHistoryResponse)
def prediction_history(
    model: str = Query("market_avg_odds", min_length=1, max_length=120),
    limit: int = Query(50, ge=1, le=200),
    status: str = Query("all", pattern="^(all|evaluated|pending)$"),
    divisions: str | None = Query(None, min_length=2),
) -> PredictionHistoryResponse:
    from futpredict.db.session import SessionLocal

    division_codes = _division_codes_from_query(divisions)
    try:
        with SessionLocal() as session:
            summary = prediction_history_summary(
                session,
                model_name=model,
                division_codes=division_codes,
            )
            rows = prediction_history_rows(
                session,
                model_name=model,
                division_codes=division_codes,
                status=status,
                limit=limit,
            )
    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=503,
            detail=f"database unavailable: {exc.__class__.__name__}",
        ) from exc

    return PredictionHistoryResponse(
        model=model,
        summary=PredictionHistorySummaryResponse(
            model=str(summary["model"]),
            total=_required_int(summary["total"]),
            evaluated=_required_int(summary["evaluated"]),
            pending=_required_int(summary["pending"]),
            hits=_required_int(summary["hits"]),
            accuracy=_optional_float(summary["accuracy"]),
            avg_rps=_optional_float(summary["avg_rps"]),
        ),
        rows=[
            PredictionHistoryRowResponse(
                match_id=_required_int(row["match_id"]),
                kickoff_utc=cast(datetime, row["kickoff_utc"]),
                league=str(row["league"]),
                home_team=str(row["home_team"]),
                away_team=str(row["away_team"]),
                status=str(row["status"]),
                home_goals=_optional_int(row["home_goals"]),
                away_goals=_optional_int(row["away_goals"]),
                model=str(row["model"]),
                prob_home=_required_float(row["prob_home"]),
                prob_draw=_required_float(row["prob_draw"]),
                prob_away=_required_float(row["prob_away"]),
                predicted_outcome=str(row["predicted_outcome"]),
                predicted_pick=str(row["predicted_pick"]),
                actual_outcome=_optional_str(row["actual_outcome"]),
                hit=_optional_bool(row["hit"]),
                rps=_optional_float(row["rps"]),
            )
            for row in rows
        ],
    )


@router.get("/calibration/status", response_model=CalibrationStatusResponse)
def calibration_status(
    bins: int = Query(10, ge=1, le=50),
) -> CalibrationStatusResponse:
    from futpredict.db.session import SessionLocal

    try:
        with SessionLocal() as session:
            rows = calibration_status_rows(session, n_bins=bins)
    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=503,
            detail=f"database unavailable: {exc.__class__.__name__}",
        ) from exc

    return CalibrationStatusResponse(
        n_bins=bins,
        rows=[
            CalibrationStatusRowResponse(
                model=str(row["model"]),
                algorithm=str(row["algorithm"]),
                feature_set_version=str(row["feature_set_version"]),
                model_versions=_required_int(row["model_versions"]),
                bins=_required_int(row["bins"]),
                class_samples=_required_int(row["class_samples"]),
                calibration_error=_optional_float(row["calibration_error"]),
            )
            for row in rows
        ],
    )


@router.get("/calibration/curves", response_model=CalibrationCurveResponse)
def calibration_curves(
    bins: int = Query(10, ge=1, le=50),
    model: str | None = Query(None, min_length=1, max_length=120),
) -> CalibrationCurveResponse:
    from futpredict.db.session import SessionLocal

    try:
        with SessionLocal() as session:
            rows = calibration_curve_rows(session, n_bins=bins, model_name=model)
    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=503,
            detail=f"database unavailable: {exc.__class__.__name__}",
        ) from exc

    return CalibrationCurveResponse(
        n_bins=bins,
        model=model,
        rows=[
            CalibrationCurvePointResponse(
                model=str(row["model"]),
                algorithm=str(row["algorithm"]),
                feature_set_version=str(row["feature_set_version"]),
                outcome=str(row["outcome"]),
                n_bins=_required_int(row["n_bins"]),
                bin_index=_required_int(row["bin_index"]),
                bin_lower=_required_float(row["bin_lower"]),
                bin_upper=_required_float(row["bin_upper"]),
                n_predictions=_required_int(row["n_predictions"]),
                avg_predicted_probability=_required_float(row["avg_predicted_probability"]),
                observed_frequency=_required_float(row["observed_frequency"]),
                calibration_error=_required_float(row["calibration_error"]),
            )
            for row in rows
        ],
    )


@router.get("/models/rankings", response_model=ModelRankingResponse)
def model_rankings(
    min_matches: int = Query(100, ge=1),
    divisions: str | None = Query(None, min_length=2),
) -> ModelRankingResponse:
    from futpredict.db.session import SessionLocal

    division_codes = _division_codes_from_query(divisions)
    try:
        with SessionLocal() as session:
            rows = model_ranking_rows(
                session,
                min_matches=min_matches,
                division_codes=division_codes,
            )
    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=503,
            detail=f"database unavailable: {exc.__class__.__name__}",
        ) from exc

    return ModelRankingResponse(rows=[_model_ranking_response(row) for row in rows])


@router.get("/models/champion", response_model=ModelRankingRowResponse)
def champion_model(
    min_matches: int = Query(100, ge=1),
) -> ModelRankingRowResponse:
    from futpredict.db.session import SessionLocal

    try:
        with SessionLocal() as session:
            row = champion_model_row(session, min_matches=min_matches)
    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=503,
            detail=f"database unavailable: {exc.__class__.__name__}",
        ) from exc
    if row is None:
        raise HTTPException(status_code=404, detail="no ranked models available")
    return _model_ranking_response(row)


@router.get("/fixtures/upcoming", response_model=UpcomingFixturesResponse)
def upcoming_fixtures(
    days: int = Query(14, ge=1, le=120),
    since_days: int = Query(0, ge=0, le=60),
    limit: int = Query(50, ge=1, le=200),
    divisions: str | None = Query(None, min_length=2),
) -> UpcomingFixturesResponse:
    from futpredict.db.session import SessionLocal

    generated_at = datetime.now(UTC)
    division_codes = _division_codes_from_query(divisions)
    try:
        with SessionLocal() as session:
            fixtures = load_upcoming_fixtures_from_db(
                session,
                start_at=generated_at - timedelta(days=since_days),
                end_at=generated_at + timedelta(days=days),
                division_codes=division_codes,
                limit=limit,
            )
    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=503,
            detail=f"database unavailable: {exc.__class__.__name__}",
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return UpcomingFixturesResponse(
        generated_at=generated_at,
        days=days,
        rows=[_fixture_response(fixture) for fixture in fixtures],
    )


@router.get("/fixtures/predictions", response_model=FixturePredictionsResponse)
def fixture_predictions(
    days: int = Query(14, ge=1, le=120),
    since_days: int = Query(0, ge=0, le=60),
    limit: int = Query(50, ge=1, le=200),
    model: str = Query("best_available", min_length=1, max_length=120),
    divisions: str | None = Query(None, min_length=2),
) -> FixturePredictionsResponse:
    from futpredict.db.session import SessionLocal

    generated_at = datetime.now(UTC)
    division_codes = _division_codes_from_query(divisions)
    model_names = _future_model_names(model)
    try:
        with SessionLocal() as session:
            fixtures = load_upcoming_fixtures_from_db(
                session,
                start_at=generated_at - timedelta(days=since_days),
                end_at=generated_at + timedelta(days=days),
                division_codes=division_codes,
                limit=limit,
            )
            training_matches = load_finished_match_results_before_from_db(
                session,
                cutoff_utc=generated_at,
                division_codes=division_codes,
            )
            rankings = model_ranking_rows(session, min_matches=100)
    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=503,
            detail=f"database unavailable: {exc.__class__.__name__}",
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    predictions = build_fixture_predictions(
        fixtures,
        training_matches,
        model_names=model_names,
    )
    ranking_by_model = {str(row["model"]): row for row in rankings}
    grouped_predictions = _group_fixture_predictions(predictions)
    rows = [
        FixturePredictionRowResponse(
            fixture=_fixture_response(fixture),
            predictions=_fixture_prediction_responses(
                grouped_predictions.get(_fixture_key(fixture), []),
                ranking_by_model=ranking_by_model,
                model_mode=model,
            ),
        )
        for fixture in fixtures
    ]

    return FixturePredictionsResponse(
        generated_at=generated_at,
        days=days,
        model_mode=model,
        rows=rows,
    )


@router.get("/matches/{match_id}", response_model=MatchDetailResponse)
def match_detail(match_id: int) -> MatchDetailResponse:
    from futpredict.db.session import SessionLocal

    try:
        with SessionLocal() as session:
            detail = load_match_detail(session, match_id)
    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=503,
            detail=f"database unavailable: {exc.__class__.__name__}",
        ) from exc
    if detail is None:
        raise HTTPException(status_code=404, detail="match not found")

    return MatchDetailResponse(
        match_id=_required_int(detail["match_id"]),
        kickoff_utc=cast(datetime, detail["kickoff_utc"]),
        league=str(detail["league"]),
        division=str(detail["division"]),
        season=str(detail["season"]),
        status=str(detail["status"]),
        home_team=str(detail["home_team"]),
        away_team=str(detail["away_team"]),
        home_goals=_optional_int(detail["home_goals"]),
        away_goals=_optional_int(detail["away_goals"]),
        odds_home=_optional_float(detail["odds_home"]),
        odds_draw=_optional_float(detail["odds_draw"]),
        odds_away=_optional_float(detail["odds_away"]),
        implied=cast("list[float] | None", detail["implied"]),
        home_elo_before=_optional_float(detail["home_elo_before"]),
        away_elo_before=_optional_float(detail["away_elo_before"]),
        xg=cast("dict[str, float | None]", detail["xg"]),
        home_form=cast("list[str]", detail["home_form"]),
        away_form=cast("list[str]", detail["away_form"]),
        head_to_head=[
            MatchDetailHeadToHeadResponse(
                kickoff_utc=cast(datetime, item["kickoff_utc"]),
                home_team=str(item["home_team"]),
                away_team=str(item["away_team"]),
                home_goals=_required_int(item["home_goals"]),
                away_goals=_required_int(item["away_goals"]),
            )
            for item in cast("list[dict[str, object]]", detail["head_to_head"])
        ],
    )


def _load_football_data_uk_matches(seasons: list[str], divisions: list[str]) -> list[MatchResult]:
    try:
        return load_matches(
            seasons=seasons,
            divisions=divisions,
            cache_dir=Path("data/raw/football-data-uk"),
        )
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"data source unavailable: {exc}") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _load_db_matches(
    *,
    start_season: str,
    end_season: str,
    divisions: list[str],
) -> list[MatchResult]:
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
        raise HTTPException(
            status_code=503,
            detail=f"database unavailable: {exc.__class__.__name__}",
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _backtest_response(
    scope: str,
    source: str,
    start_season: str,
    end_season: str,
    divisions: list[str],
    matches: list[MatchResult],
) -> BacktestResponse:
    prediction_rows = run_baseline_backtest(matches)
    metrics = summarize_predictions(prediction_rows)
    breakdowns = [
        *summarize_prediction_breakdowns(
            prediction_rows,
            group_type="division",
            key_func=lambda match: match.division,
        ),
        *summarize_prediction_breakdowns(
            prediction_rows,
            group_type="season",
            key_func=lambda match: match.season,
        ),
    ]
    return BacktestResponse(
        scope=scope,
        source=source,
        start_season=start_season,
        end_season=end_season,
        divisions=divisions,
        n_matches=len(matches),
        metrics=_metric_responses(metrics),
        breakdowns=[
            BacktestBreakdownResponse(
                group_type=breakdown.group_type,
                group_key=breakdown.group_key,
                n_matches=breakdown.n_matches,
                metrics=_metric_responses(breakdown.metrics),
            )
            for breakdown in breakdowns
        ],
    )


def _metric_responses(metrics: list[MetricSummary]) -> list[BacktestMetricResponse]:
    return [
        BacktestMetricResponse(
            model=summary.model,
            n_matches=summary.n_matches,
            rps=summary.rps,
            log_loss=summary.log_loss,
            brier=summary.brier,
            accuracy=summary.accuracy,
        )
        for summary in metrics
    ]


def _model_ranking_response(row: dict[str, object]) -> ModelRankingRowResponse:
    return ModelRankingRowResponse(
        model=str(row["model"]),
        algorithm=str(row["algorithm"]),
        feature_set_version=str(row["feature_set_version"]),
        windows=_required_int(row["windows"]),
        matches=_required_int(row["matches"]),
        weighted_rps=_required_float(row["weighted_rps"]),
        weighted_log_loss=_optional_float(row["weighted_log_loss"]),
        weighted_brier=_optional_float(row["weighted_brier"]),
        weighted_accuracy=_optional_float(row["weighted_accuracy"]),
        weighted_calibration_error=_optional_float(row["weighted_calibration_error"]),
    )


def _fixture_response(fixture: Fixture) -> FixtureResponse:
    return FixtureResponse(
        match_id=fixture.match_id,
        kickoff_utc=fixture.kickoff_utc,
        season=fixture.season,
        division=fixture.division,
        home_team=fixture.home_team,
        away_team=fixture.away_team,
        status=fixture.status,
        avg_home_odds=fixture.avg_home_odds,
        avg_draw_odds=fixture.avg_draw_odds,
        avg_away_odds=fixture.avg_away_odds,
        odds_source=fixture.odds_source,
    )


def _future_model_names(model_mode: str) -> list[str]:
    normalized = model_mode.strip()
    if normalized in {"all", "best_available"}:
        return list(SUPPORTED_FUTURE_MODELS)
    if normalized not in SUPPORTED_FUTURE_MODELS:
        supported = ", ".join(["all", "best_available", *SUPPORTED_FUTURE_MODELS])
        msg = f"unsupported model mode {normalized!r}; supported values: {supported}"
        raise ValueError(msg)
    return [normalized]


def _fixture_prediction_responses(
    predictions: Sequence[FixturePrediction],
    *,
    ranking_by_model: dict[str, dict[str, object]],
    model_mode: str,
) -> list[FixtureModelPredictionResponse]:
    ranking_order = {model_name: index for index, model_name in enumerate(ranking_by_model)}
    ordered = sorted(
        predictions,
        key=lambda prediction: (
            ranking_order.get(prediction.model, len(ranking_order) + 1),
            _future_model_index(prediction.model),
        ),
    )
    if model_mode == "best_available":
        ordered = ordered[:1]

    rows: list[FixtureModelPredictionResponse] = []
    for index, prediction in enumerate(ordered):
        ranking = ranking_by_model.get(prediction.model)
        prob_home, prob_draw, prob_away = prediction.probabilities
        rows.append(
            FixtureModelPredictionResponse(
                model=prediction.model,
                algorithm=prediction.algorithm,
                feature_set_version=prediction.feature_set_version,
                prob_home=prob_home,
                prob_draw=prob_draw,
                prob_away=prob_away,
                train_window_start_utc=prediction.train_window_start_utc,
                train_window_end_utc=prediction.train_window_end_utc,
                ranking_rps=_optional_float(ranking.get("weighted_rps")) if ranking else None,
                ranking_calibration_error=(
                    _optional_float(ranking.get("weighted_calibration_error"))
                    if ranking
                    else None
                ),
                is_recommended=index == 0,
            )
        )
    return rows


def _group_fixture_predictions(
    predictions: Sequence[FixturePrediction],
) -> dict[tuple[int | None, datetime, str, str, str], list[FixturePrediction]]:
    grouped: dict[tuple[int | None, datetime, str, str, str], list[FixturePrediction]] = {}
    for prediction in predictions:
        grouped.setdefault(_fixture_key(prediction.fixture), []).append(prediction)
    return grouped


def _fixture_key(fixture: Fixture) -> tuple[int | None, datetime, str, str, str]:
    return (
        fixture.match_id,
        fixture.kickoff_utc,
        fixture.division,
        fixture.home_team,
        fixture.away_team,
    )


def _future_model_index(model_name: str) -> int:
    try:
        return list(SUPPORTED_FUTURE_MODELS).index(model_name)
    except ValueError:
        return len(SUPPORTED_FUTURE_MODELS)


def _division_codes_from_query(value: str | None) -> list[str] | None:
    if value is None:
        return None
    divisions = [item.strip().upper() for item in value.split(",") if item.strip()]
    return divisions or None


def _optional_float(value: object) -> float | None:
    if value is None:
        return None
    return _required_float(value)


def _required_float(value: object) -> float:
    if isinstance(value, Decimal | int | float):
        return float(value)
    return float(str(value))


def _required_int(value: object) -> int:
    if isinstance(value, int):
        return value
    if isinstance(value, Decimal | float):
        return int(value)
    return int(str(value))


def _optional_int(value: object) -> int | None:
    if value is None:
        return None
    return _required_int(value)


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    return str(value)


def _optional_bool(value: object) -> bool | None:
    if value is None:
        return None
    return bool(value)

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: str
    app_env: str


class BacktestMetricResponse(BaseModel):
    model: str
    n_matches: int
    rps: float
    log_loss: float
    brier: float
    accuracy: float


class BacktestBreakdownResponse(BaseModel):
    group_type: str
    group_key: str
    n_matches: int
    metrics: list[BacktestMetricResponse]


class BacktestResponse(BaseModel):
    scope: str
    source: str
    start_season: str
    end_season: str
    divisions: list[str]
    n_matches: int
    metrics: list[BacktestMetricResponse]
    breakdowns: list[BacktestBreakdownResponse]


class PredictionStatusRowResponse(BaseModel):
    model: str
    algorithm: str
    feature_set_version: str
    predictions: int
    evaluated: int
    avg_rps: float | None
    avg_log_loss: float | None
    avg_brier: float | None


class PredictionStatusResponse(BaseModel):
    rows: list[PredictionStatusRowResponse]


class CalibrationStatusRowResponse(BaseModel):
    model: str
    algorithm: str
    feature_set_version: str
    model_versions: int
    bins: int
    class_samples: int
    calibration_error: float | None


class CalibrationStatusResponse(BaseModel):
    n_bins: int
    rows: list[CalibrationStatusRowResponse]


class CalibrationCurvePointResponse(BaseModel):
    model: str
    algorithm: str
    feature_set_version: str
    outcome: str
    n_bins: int
    bin_index: int
    bin_lower: float
    bin_upper: float
    n_predictions: int
    avg_predicted_probability: float
    observed_frequency: float
    calibration_error: float


class CalibrationCurveResponse(BaseModel):
    n_bins: int
    model: str | None
    rows: list[CalibrationCurvePointResponse]


class ModelRankingRowResponse(BaseModel):
    model: str
    algorithm: str
    feature_set_version: str
    windows: int
    matches: int
    weighted_rps: float
    weighted_log_loss: float | None
    weighted_brier: float | None
    weighted_accuracy: float | None
    weighted_calibration_error: float | None


class ModelRankingResponse(BaseModel):
    rows: list[ModelRankingRowResponse]


class FixtureResponse(BaseModel):
    match_id: int | None
    kickoff_utc: datetime
    season: str
    division: str
    home_team: str
    away_team: str
    status: str
    avg_home_odds: float | None
    avg_draw_odds: float | None
    avg_away_odds: float | None
    odds_source: str | None


class UpcomingFixturesResponse(BaseModel):
    generated_at: datetime
    days: int
    rows: list[FixtureResponse]


class FixtureModelPredictionResponse(BaseModel):
    model: str
    algorithm: str
    feature_set_version: str
    prob_home: float
    prob_draw: float
    prob_away: float
    train_window_start_utc: datetime | None
    train_window_end_utc: datetime | None
    ranking_rps: float | None
    ranking_calibration_error: float | None
    is_recommended: bool


class FixturePredictionRowResponse(BaseModel):
    fixture: FixtureResponse
    predictions: list[FixtureModelPredictionResponse]


class FixturePredictionsResponse(BaseModel):
    generated_at: datetime
    days: int
    model_mode: str
    rows: list[FixturePredictionRowResponse]


class PredictionHistoryRowResponse(BaseModel):
    match_id: int
    kickoff_utc: datetime
    league: str
    home_team: str
    away_team: str
    status: str
    home_goals: int | None
    away_goals: int | None
    model: str
    prob_home: float
    prob_draw: float
    prob_away: float
    predicted_outcome: str
    predicted_pick: str
    actual_outcome: str | None
    hit: bool | None
    rps: float | None


class PredictionHistorySummaryResponse(BaseModel):
    model: str
    total: int
    evaluated: int
    pending: int
    hits: int
    accuracy: float | None
    avg_rps: float | None


class PredictionHistoryResponse(BaseModel):
    model: str
    summary: PredictionHistorySummaryResponse
    rows: list[PredictionHistoryRowResponse]

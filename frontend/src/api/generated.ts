/* eslint-disable */
// This file is generated from src/api/openapi.json.
// Run `npm run generate:api-types` after exporting OpenAPI from the backend.

export type components = {
  schemas: {
    BacktestBreakdownResponse: {
      group_type: string;
      group_key: string;
      n_matches: number;
      metrics: components["schemas"]["BacktestMetricResponse"][];
    };
    BacktestMetricResponse: {
      model: string;
      n_matches: number;
      rps: number;
      log_loss: number;
      brier: number;
      accuracy: number;
    };
    BacktestResponse: {
      scope: string;
      source: string;
      start_season: string;
      end_season: string;
      divisions: string[];
      n_matches: number;
      metrics: components["schemas"]["BacktestMetricResponse"][];
      breakdowns: components["schemas"]["BacktestBreakdownResponse"][];
    };
    CalibrationCurvePointResponse: {
      model: string;
      algorithm: string;
      feature_set_version: string;
      outcome: string;
      n_bins: number;
      bin_index: number;
      bin_lower: number;
      bin_upper: number;
      n_predictions: number;
      avg_predicted_probability: number;
      observed_frequency: number;
      calibration_error: number;
    };
    CalibrationCurveResponse: {
      n_bins: number;
      model: string | null;
      rows: components["schemas"]["CalibrationCurvePointResponse"][];
    };
    CalibrationStatusResponse: {
      n_bins: number;
      rows: components["schemas"]["CalibrationStatusRowResponse"][];
    };
    CalibrationStatusRowResponse: {
      model: string;
      algorithm: string;
      feature_set_version: string;
      model_versions: number;
      bins: number;
      class_samples: number;
      calibration_error: number | null;
    };
    FixtureModelPredictionResponse: {
      model: string;
      algorithm: string;
      feature_set_version: string;
      prob_home: number;
      prob_draw: number;
      prob_away: number;
      train_window_start_utc: string | null;
      train_window_end_utc: string | null;
      ranking_rps: number | null;
      ranking_calibration_error: number | null;
      is_recommended: boolean;
    };
    FixturePredictionRowResponse: {
      fixture: components["schemas"]["FixtureResponse"];
      predictions: components["schemas"]["FixtureModelPredictionResponse"][];
    };
    FixturePredictionsResponse: {
      generated_at: string;
      days: number;
      model_mode: string;
      rows: components["schemas"]["FixturePredictionRowResponse"][];
    };
    FixtureResponse: {
      match_id: number | null;
      kickoff_utc: string;
      season: string;
      division: string;
      home_team: string;
      away_team: string;
      status: string;
      avg_home_odds: number | null;
      avg_draw_odds: number | null;
      avg_away_odds: number | null;
      odds_source: string | null;
    };
    HTTPValidationError: {
      detail?: components["schemas"]["ValidationError"][];
    };
    HealthResponse: {
      status: string;
      app_env: string;
    };
    MatchDetailHeadToHeadResponse: {
      kickoff_utc: string;
      home_team: string;
      away_team: string;
      home_goals: number;
      away_goals: number;
    };
    MatchDetailResponse: {
      match_id: number;
      kickoff_utc: string;
      league: string;
      division: string;
      season: string;
      status: string;
      home_team: string;
      away_team: string;
      home_goals: number | null;
      away_goals: number | null;
      odds_home: number | null;
      odds_draw: number | null;
      odds_away: number | null;
      implied: number[] | null;
      home_elo_before: number | null;
      away_elo_before: number | null;
      xg: {
      [key: string]: number | null;
    };
      home_form: string[];
      away_form: string[];
      head_to_head: components["schemas"]["MatchDetailHeadToHeadResponse"][];
    };
    ModelRankingResponse: {
      rows: components["schemas"]["ModelRankingRowResponse"][];
    };
    ModelRankingRowResponse: {
      model: string;
      algorithm: string;
      feature_set_version: string;
      windows: number;
      matches: number;
      weighted_rps: number;
      weighted_log_loss: number | null;
      weighted_brier: number | null;
      weighted_accuracy: number | null;
      weighted_calibration_error: number | null;
    };
    PredictionHistoryResponse: {
      model: string;
      summary: components["schemas"]["PredictionHistorySummaryResponse"];
      rows: components["schemas"]["PredictionHistoryRowResponse"][];
    };
    PredictionHistoryRowResponse: {
      match_id: number;
      kickoff_utc: string;
      league: string;
      home_team: string;
      away_team: string;
      status: string;
      home_goals: number | null;
      away_goals: number | null;
      model: string;
      prob_home: number;
      prob_draw: number;
      prob_away: number;
      predicted_outcome: string;
      predicted_pick: string;
      actual_outcome: string | null;
      hit: boolean | null;
      rps: number | null;
    };
    PredictionHistorySummaryResponse: {
      model: string;
      total: number;
      evaluated: number;
      pending: number;
      hits: number;
      accuracy: number | null;
      avg_rps: number | null;
    };
    PredictionStatusResponse: {
      rows: components["schemas"]["PredictionStatusRowResponse"][];
    };
    PredictionStatusRowResponse: {
      model: string;
      algorithm: string;
      feature_set_version: string;
      predictions: number;
      evaluated: number;
      avg_rps: number | null;
      avg_log_loss: number | null;
      avg_brier: number | null;
    };
    UpcomingFixturesResponse: {
      generated_at: string;
      days: number;
      rows: components["schemas"]["FixtureResponse"][];
    };
    ValidationError: {
      loc: (string | number)[];
      msg: string;
      type: string;
      input?: unknown;
      ctx?: Record<string, never>;
    };
  };
};

export type BacktestBreakdownResponse = components["schemas"]["BacktestBreakdownResponse"];
export type BacktestMetricResponse = components["schemas"]["BacktestMetricResponse"];
export type BacktestResponse = components["schemas"]["BacktestResponse"];
export type CalibrationCurvePointResponse = components["schemas"]["CalibrationCurvePointResponse"];
export type CalibrationCurveResponse = components["schemas"]["CalibrationCurveResponse"];
export type CalibrationStatusResponse = components["schemas"]["CalibrationStatusResponse"];
export type CalibrationStatusRowResponse = components["schemas"]["CalibrationStatusRowResponse"];
export type FixtureModelPredictionResponse = components["schemas"]["FixtureModelPredictionResponse"];
export type FixturePredictionRowResponse = components["schemas"]["FixturePredictionRowResponse"];
export type FixturePredictionsResponse = components["schemas"]["FixturePredictionsResponse"];
export type FixtureResponse = components["schemas"]["FixtureResponse"];
export type HTTPValidationError = components["schemas"]["HTTPValidationError"];
export type HealthResponse = components["schemas"]["HealthResponse"];
export type MatchDetailHeadToHeadResponse = components["schemas"]["MatchDetailHeadToHeadResponse"];
export type MatchDetailResponse = components["schemas"]["MatchDetailResponse"];
export type ModelRankingResponse = components["schemas"]["ModelRankingResponse"];
export type ModelRankingRowResponse = components["schemas"]["ModelRankingRowResponse"];
export type PredictionHistoryResponse = components["schemas"]["PredictionHistoryResponse"];
export type PredictionHistoryRowResponse = components["schemas"]["PredictionHistoryRowResponse"];
export type PredictionHistorySummaryResponse = components["schemas"]["PredictionHistorySummaryResponse"];
export type PredictionStatusResponse = components["schemas"]["PredictionStatusResponse"];
export type PredictionStatusRowResponse = components["schemas"]["PredictionStatusRowResponse"];
export type UpcomingFixturesResponse = components["schemas"]["UpcomingFixturesResponse"];
export type ValidationError = components["schemas"]["ValidationError"];

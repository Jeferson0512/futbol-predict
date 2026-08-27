from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from futpredict.data.football_data_uk_catalog import season_range
from futpredict.domain.matches import MatchResult
from futpredict.evaluation.backtest import (
    MetricSummary,
    PredictionProvider,
    run_baseline_backtest,
    summarize_predictions,
)

DEFAULT_INITIAL_TRAIN_SEASONS = 3
type MetricField = Literal["rps", "log_loss", "brier", "accuracy"]


@dataclass(frozen=True)
class WalkForwardMetric:
    division: str
    evaluation_season: str
    train_start_season: str
    train_end_season: str
    train_window_start_utc: datetime
    train_window_end_utc: datetime
    eval_window_start_utc: datetime
    eval_window_end_utc: datetime
    summary: MetricSummary

    @property
    def window_label(self) -> str:
        return (
            f"eval_{self.evaluation_season}_"
            f"train_{self.train_start_season}_{self.train_end_season}"
        )


def run_expanding_walk_forward(
    matches: Iterable[MatchResult],
    *,
    start_season: str,
    end_season: str,
    initial_train_seasons: int = DEFAULT_INITIAL_TRAIN_SEASONS,
    extra_prediction_providers: Sequence[PredictionProvider] | None = None,
) -> list[WalkForwardMetric]:
    seasons = season_range(start_season, end_season)
    if initial_train_seasons < 1:
        msg = "initial_train_seasons must be positive"
        raise ValueError(msg)
    if len(seasons) <= initial_train_seasons:
        msg = "season range must leave at least one evaluation season"
        raise ValueError(msg)

    materialized = [match for match in matches if match.season in set(seasons)]
    by_division: dict[str, list[MatchResult]] = {}
    for match in materialized:
        by_division.setdefault(match.division, []).append(match)

    metrics: list[WalkForwardMetric] = []
    for division, division_matches in sorted(by_division.items()):
        ordered_division_matches = sorted(division_matches, key=lambda match: match.kickoff_utc)
        for eval_index in range(initial_train_seasons, len(seasons)):
            train_seasons = set(seasons[:eval_index])
            eval_season = seasons[eval_index]
            train_matches = [
                match for match in ordered_division_matches if match.season in train_seasons
            ]
            eval_matches = [
                match for match in ordered_division_matches if match.season == eval_season
            ]
            if not train_matches or not eval_matches:
                continue

            train_and_eval = [*train_matches, *eval_matches]
            prediction_rows = run_baseline_backtest(
                train_and_eval,
                isolate_by_division=False,
                extra_prediction_providers=extra_prediction_providers,
            )
            eval_rows = [row for row in prediction_rows if row.match.season == eval_season]
            for summary in summarize_predictions(eval_rows):
                metrics.append(
                    WalkForwardMetric(
                        division=division,
                        evaluation_season=eval_season,
                        train_start_season=seasons[0],
                        train_end_season=seasons[eval_index - 1],
                        train_window_start_utc=train_matches[0].kickoff_utc,
                        train_window_end_utc=train_matches[-1].kickoff_utc,
                        eval_window_start_utc=eval_matches[0].kickoff_utc,
                        eval_window_end_utc=eval_matches[-1].kickoff_utc,
                        summary=summary,
                    )
                )
    return metrics


def summarize_walk_forward_metrics(metrics: Iterable[WalkForwardMetric]) -> list[MetricSummary]:
    grouped: dict[str, list[MetricSummary]] = {}
    for metric in metrics:
        grouped.setdefault(metric.summary.model, []).append(metric.summary)

    summaries: list[MetricSummary] = []
    for model, rows in grouped.items():
        n_matches = sum(row.n_matches for row in rows)
        if n_matches == 0:
            continue
        summaries.append(
            MetricSummary(
                model=model,
                n_matches=n_matches,
                rps=_weighted_average(rows, "rps"),
                log_loss=_weighted_average(rows, "log_loss"),
                brier=_weighted_average(rows, "brier"),
                accuracy=_weighted_average(rows, "accuracy"),
            )
        )
    return sorted(summaries, key=lambda summary: summary.rps)


def _weighted_average(rows: list[MetricSummary], field_name: MetricField) -> float:
    total_matches = sum(row.n_matches for row in rows)
    weighted_sum = sum(_metric_value(row, field_name) * row.n_matches for row in rows)
    return weighted_sum / total_matches


def _metric_value(row: MetricSummary, field_name: MetricField) -> float:
    if field_name == "rps":
        return row.rps
    if field_name == "log_loss":
        return row.log_loss
    if field_name == "brier":
        return row.brier
    return row.accuracy

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from statistics import fmean

from futpredict.domain.matches import MatchResult
from futpredict.evaluation.metrics import accuracy, brier_score
from futpredict.evaluation.metrics import log_loss as log_loss_metric
from futpredict.evaluation.rps import ranked_probability_score
from futpredict.models.baseline import historical_frequency_probabilities
from futpredict.models.elo import EloConfig, expected_home_score, update_elo


@dataclass(frozen=True)
class PredictionRow:
    model: str
    match: MatchResult
    probabilities: tuple[float, float, float]


PredictionProvider = Callable[[MatchResult], PredictionRow | None]


@dataclass(frozen=True)
class MetricSummary:
    model: str
    n_matches: int
    rps: float
    log_loss: float
    brier: float
    accuracy: float


@dataclass(frozen=True)
class BreakdownSummary:
    group_type: str
    group_key: str
    n_matches: int
    metrics: list[MetricSummary]


def run_baseline_backtest(
    matches: Iterable[MatchResult],
    elo_config: EloConfig | None = None,
    initial_rating: float = 1500.0,
    isolate_by_division: bool = True,
    extra_prediction_providers: Sequence[PredictionProvider] | None = None,
) -> list[PredictionRow]:
    ordered = sorted(matches, key=lambda match: match.kickoff_utc)
    cfg = elo_config or EloConfig()
    rows: list[PredictionRow] = []
    ratings: dict[tuple[str, str], float] = {}
    result_counts: dict[str, list[int]] = {}
    providers = extra_prediction_providers or ()

    index = 0
    while index < len(ordered):
        kickoff = ordered[index].kickoff_utc
        same_cutoff_matches: list[MatchResult] = []
        while index < len(ordered) and ordered[index].kickoff_utc == kickoff:
            same_cutoff_matches.append(ordered[index])
            index += 1

        for match in same_cutoff_matches:
            group = match.division if isolate_by_division else "all"
            counts = result_counts.setdefault(group, [0, 0, 0])
            rows.append(PredictionRow("always_home", match, (1.0, 0.0, 0.0)))
            rows.append(
                PredictionRow(
                    "historical_frequency",
                    match,
                    historical_frequency_probabilities(counts[0], counts[1], counts[2]),
                )
            )
            market = market_probabilities(match)
            if market is not None:
                rows.append(PredictionRow("market_avg_odds", match, market))

            home_key = (group, match.home_team)
            away_key = (group, match.away_team)
            home_rating = ratings.get(home_key, initial_rating)
            away_rating = ratings.get(away_key, initial_rating)
            home_expected = expected_home_score(home_rating, away_rating, cfg.home_advantage)
            draw_probability = 0.26
            decisive_probability = 1.0 - draw_probability
            elo_probabilities = (
                home_expected * decisive_probability,
                draw_probability,
                (1.0 - home_expected) * decisive_probability,
            )
            rows.append(PredictionRow("elo_simple", match, elo_probabilities))
            for provider in providers:
                extra_prediction = provider(match)
                if extra_prediction is not None:
                    rows.append(extra_prediction)

        for match in same_cutoff_matches:
            group = match.division if isolate_by_division else "all"
            counts = result_counts[group]
            if match.outcome == "H":
                counts[0] += 1
            elif match.outcome == "D":
                counts[1] += 1
            else:
                counts[2] += 1

            home_key = (group, match.home_team)
            away_key = (group, match.away_team)
            home_rating = ratings.get(home_key, initial_rating)
            away_rating = ratings.get(away_key, initial_rating)
            new_home, new_away = update_elo(
                home_rating,
                away_rating,
                match.home_goals,
                match.away_goals,
                cfg,
            )
            ratings[home_key] = new_home
            ratings[away_key] = new_away

    return rows


def summarize_predictions(rows: Iterable[PredictionRow]) -> list[MetricSummary]:
    grouped: dict[str, list[PredictionRow]] = {}
    for row in rows:
        grouped.setdefault(row.model, []).append(row)

    summaries: list[MetricSummary] = []
    for model, model_rows in grouped.items():
        rps_values = [
            ranked_probability_score(row.probabilities, row.match.outcome) for row in model_rows
        ]
        log_loss_values = [
            log_loss_metric(row.probabilities, row.match.outcome) for row in model_rows
        ]
        brier_values = [brier_score(row.probabilities, row.match.outcome) for row in model_rows]
        accuracy_values = [accuracy(row.probabilities, row.match.outcome) for row in model_rows]
        summaries.append(
            MetricSummary(
                model=model,
                n_matches=len(model_rows),
                rps=fmean(rps_values),
                log_loss=fmean(log_loss_values),
                brier=fmean(brier_values),
                accuracy=fmean(accuracy_values),
            )
        )
    return sorted(summaries, key=lambda summary: summary.rps)


def summarize_prediction_breakdowns(
    rows: Iterable[PredictionRow],
    group_type: str,
    key_func: Callable[[MatchResult], str],
) -> list[BreakdownSummary]:
    grouped_rows: dict[str, list[PredictionRow]] = {}
    grouped_matches: dict[str, set[MatchResult]] = {}
    for row in rows:
        group_key = key_func(row.match)
        grouped_rows.setdefault(group_key, []).append(row)
        grouped_matches.setdefault(group_key, set()).add(row.match)

    return [
        BreakdownSummary(
            group_type=group_type,
            group_key=group_key,
            n_matches=len(grouped_matches[group_key]),
            metrics=summarize_predictions(grouped_rows[group_key]),
        )
        for group_key in sorted(grouped_rows)
    ]


def backtest_summary(matches: Iterable[MatchResult]) -> list[MetricSummary]:
    materialized = list(matches)
    if not materialized:
        raise ValueError("cannot backtest an empty match collection")
    return summarize_predictions(run_baseline_backtest(materialized))


def market_probabilities(match: MatchResult) -> tuple[float, float, float] | None:
    if match.avg_home_odds is None or match.avg_draw_odds is None or match.avg_away_odds is None:
        return None
    if match.avg_home_odds <= 1.0 or match.avg_draw_odds <= 1.0 or match.avg_away_odds <= 1.0:
        return None
    implied = (1 / match.avg_home_odds, 1 / match.avg_draw_odds, 1 / match.avg_away_odds)
    total = sum(implied)
    return (implied[0] / total, implied[1] / total, implied[2] / total)

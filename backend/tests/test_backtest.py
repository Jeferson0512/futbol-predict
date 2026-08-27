from __future__ import annotations

from datetime import UTC, datetime

from futpredict.domain.matches import MatchResult
from futpredict.evaluation.backtest import (
    PredictionRow,
    backtest_summary,
    market_probabilities,
    run_baseline_backtest,
    summarize_prediction_breakdowns,
)


def test_backtest_summary_orders_by_rps() -> None:
    matches = [
        MatchResult(datetime(2026, 1, 1, tzinfo=UTC), "2526", "E0", "A", "B", 2, 1, "H"),
        MatchResult(datetime(2026, 1, 2, tzinfo=UTC), "2526", "E0", "C", "D", 1, 1, "D"),
        MatchResult(datetime(2026, 1, 3, tzinfo=UTC), "2526", "E0", "B", "A", 0, 1, "A"),
    ]
    summaries = backtest_summary(matches)
    assert {summary.model for summary in summaries} == {
        "always_home",
        "historical_frequency",
        "elo_simple",
    }
    assert all(summary.n_matches == 3 for summary in summaries)
    assert summaries == sorted(summaries, key=lambda summary: summary.rps)


def test_market_probabilities_remove_bookmaker_margin() -> None:
    match = MatchResult(
        kickoff_utc=datetime(2026, 1, 1, tzinfo=UTC),
        season="2526",
        division="E0",
        home_team="A",
        away_team="B",
        home_goals=2,
        away_goals=1,
        outcome="H",
        avg_home_odds=2.0,
        avg_draw_odds=4.0,
        avg_away_odds=4.0,
    )
    probabilities = market_probabilities(match)
    assert probabilities == (0.5, 0.25, 0.25)


def test_backtest_includes_market_when_odds_exist() -> None:
    match = MatchResult(
        kickoff_utc=datetime(2026, 1, 1, tzinfo=UTC),
        season="2526",
        division="E0",
        home_team="A",
        away_team="B",
        home_goals=2,
        away_goals=1,
        outcome="H",
        avg_home_odds=2.0,
        avg_draw_odds=4.0,
        avg_away_odds=4.0,
    )
    rows = run_baseline_backtest([match])
    assert "market_avg_odds" in {row.model for row in rows}


def test_backtest_accepts_extra_prediction_provider() -> None:
    match = MatchResult(
        kickoff_utc=datetime(2026, 1, 1, tzinfo=UTC),
        season="2526",
        division="E0",
        home_team="A",
        away_team="B",
        home_goals=2,
        away_goals=1,
        outcome="H",
    )

    rows = run_baseline_backtest(
        [match],
        extra_prediction_providers=(
            lambda row_match: PredictionRow("external_model", row_match, (0.4, 0.3, 0.3)),
        ),
    )

    assert "external_model" in {row.model for row in rows}


def test_backtest_does_not_leak_same_cutoff_results_into_historical_frequency() -> None:
    kickoff = datetime(2026, 1, 1, tzinfo=UTC)
    matches = [
        MatchResult(kickoff, "2526", "E0", "A", "B", 2, 1, "H"),
        MatchResult(kickoff, "2526", "E0", "C", "D", 1, 1, "D"),
    ]

    historical_rows = [
        row for row in run_baseline_backtest(matches) if row.model == "historical_frequency"
    ]

    assert [row.probabilities for row in historical_rows] == [
        (1.0 / 3.0, 1.0 / 3.0, 1.0 / 3.0),
        (1.0 / 3.0, 1.0 / 3.0, 1.0 / 3.0),
    ]


def test_market_probabilities_ignore_invalid_odds() -> None:
    match = MatchResult(
        kickoff_utc=datetime(2026, 1, 1, tzinfo=UTC),
        season="2526",
        division="E0",
        home_team="A",
        away_team="B",
        home_goals=2,
        away_goals=1,
        outcome="H",
        avg_home_odds=0.0,
        avg_draw_odds=4.0,
        avg_away_odds=4.0,
    )
    assert market_probabilities(match) is None


def test_prediction_breakdowns_group_existing_predictions() -> None:
    matches = [
        MatchResult(datetime(2026, 1, 1, tzinfo=UTC), "2526", "E0", "A", "B", 2, 1, "H"),
        MatchResult(datetime(2026, 1, 2, tzinfo=UTC), "2526", "SP1", "C", "D", 1, 1, "D"),
    ]
    rows = run_baseline_backtest(matches)
    breakdowns = summarize_prediction_breakdowns(
        rows,
        group_type="division",
        key_func=lambda match: match.division,
    )
    assert [item.group_key for item in breakdowns] == ["E0", "SP1"]
    assert all(item.n_matches == 1 for item in breakdowns)

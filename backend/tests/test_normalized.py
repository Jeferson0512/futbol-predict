from __future__ import annotations

from datetime import UTC, datetime

import pytest

from futpredict.domain.fixtures import Fixture
from futpredict.domain.matches import MatchResult
from futpredict.ingest.normalized import (
    build_normalized_batch,
    build_normalized_fixture_batch,
    canonical_team_name,
    summarize_normalized_batch,
    validate_normalized_batch,
)


def test_build_normalized_batch_creates_dimensions_matches_and_odds() -> None:
    batch = build_normalized_batch(
        [
            MatchResult(
                kickoff_utc=datetime(2025, 8, 15, 20, 0, tzinfo=UTC),
                season="2526",
                division="E0",
                home_team=" Liverpool ",
                away_team="Bournemouth",
                home_goals=4,
                away_goals=2,
                outcome="H",
                avg_home_odds=1.3,
                avg_draw_odds=5.4,
                avg_away_odds=9.0,
                odds_source="avg_closing",
            )
        ]
    )

    summary = summarize_normalized_batch(batch)
    assert summary.leagues == 1
    assert summary.seasons == 1
    assert summary.teams == 2
    assert summary.team_aliases == 2
    assert summary.matches == 1
    assert summary.odds == 1
    assert batch.leagues[0].code == "premier-league"
    assert batch.seasons[0].year_start == 2025
    assert batch.matches[0].home_team_key == ("premier-league", "liverpool")
    assert batch.odds[0].bookmaker == "market_average"
    assert batch.odds[0].is_closing is True


def test_normalized_validation_detects_duplicate_matches() -> None:
    match = MatchResult(
        kickoff_utc=datetime(2025, 8, 15, 20, 0, tzinfo=UTC),
        season="2526",
        division="E0",
        home_team="Liverpool",
        away_team="Bournemouth",
        home_goals=4,
        away_goals=2,
        outcome="H",
        avg_home_odds=1.3,
        avg_draw_odds=5.4,
        avg_away_odds=9.0,
        odds_source="avg_closing",
    )
    batch = build_normalized_batch([match, match])
    validation = validate_normalized_batch(batch)

    assert validation.has_errors is True
    assert len(validation.duplicate_match_keys) == 1
    assert len(validation.duplicate_odd_keys) == 1


def test_normalized_validation_tracks_missing_odds_as_warning() -> None:
    batch = build_normalized_batch(
        [
            MatchResult(
                kickoff_utc=datetime(2025, 8, 16, 12, 30, tzinfo=UTC),
                season="2526",
                division="E0",
                home_team="Aston Villa",
                away_team="Newcastle",
                home_goals=0,
                away_goals=0,
                outcome="D",
            )
        ]
    )
    validation = validate_normalized_batch(batch)

    assert validation.has_errors is False
    assert validation.has_warnings is True
    assert len(validation.missing_odds_match_keys) == 1


def test_build_normalized_fixture_batch_creates_scheduled_matches() -> None:
    batch = build_normalized_fixture_batch(
        [
            Fixture(
                kickoff_utc=datetime(2026, 8, 30, 14, 0, tzinfo=UTC),
                season="2627",
                division="E0",
                home_team="Arsenal",
                away_team="Chelsea",
                avg_home_odds=2.1,
                avg_draw_odds=3.5,
                avg_away_odds=3.4,
                odds_source="avg",
            )
        ]
    )

    assert batch.matches[0].status == "scheduled"
    assert batch.matches[0].home_goals is None
    assert batch.matches[0].away_goals is None
    assert batch.matches[0].outcome is None
    assert batch.odds[0].bookmaker == "market_average"


def test_canonical_team_name_is_stable_for_spacing_and_case() -> None:
    assert canonical_team_name("  Real   Madrid ") == "real madrid"


def test_build_normalized_batch_rejects_unknown_divisions() -> None:
    with pytest.raises(ValueError, match="unsupported division"):
        build_normalized_batch(
            [
                MatchResult(
                    kickoff_utc=datetime(2025, 8, 15, 20, 0, tzinfo=UTC),
                    season="2526",
                    division="ZZ",
                    home_team="Home",
                    away_team="Away",
                    home_goals=1,
                    away_goals=0,
                    outcome="H",
                )
            ]
        )

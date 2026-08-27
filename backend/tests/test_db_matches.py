from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from futpredict.data.db_matches import (
    division_code_for_league,
    league_codes_from_divisions,
    match_result_from_db_row,
    season_code_from_years,
)
from futpredict.db.models import League, Match, Odd, Season
from futpredict.ingest.normalized import SOURCE_NAME


def test_match_result_from_db_row_maps_persisted_match_to_backtest_input() -> None:
    kickoff = datetime(2025, 8, 15, 20, 0, tzinfo=UTC)
    league = League(
        code="premier-league",
        name="Premier League",
        country="England",
        tier=1,
        source_ids={SOURCE_NAME: "E0"},
        active=True,
    )
    season = Season(league_id=1, year_start=2025, year_end=2026)
    match = Match(
        league_id=1,
        season_id=1,
        home_team_id=1,
        away_team_id=2,
        kickoff_utc=kickoff,
        status="finished",
        home_goals=4,
        away_goals=2,
        home_ht=None,
        away_ht=None,
        home_xg=None,
        away_xg=None,
        shots={},
        shots_on_target={},
        corners={},
        cards={},
        raw={},
        source=SOURCE_NAME,
        ingested_at=kickoff,
    )
    odd = Odd(
        match_id=1,
        bookmaker="market_average",
        market="1x2",
        odd_home=Decimal("1.3000"),
        odd_draw=Decimal("5.4000"),
        odd_away=Decimal("9.0000"),
        captured_at=None,
        is_closing=True,
    )

    result = match_result_from_db_row(
        match=match,
        league=league,
        season=season,
        home_team_name="Liverpool",
        away_team_name="Bournemouth",
        odd=odd,
    )

    assert result.kickoff_utc == kickoff
    assert result.season == "2526"
    assert result.division == "E0"
    assert result.home_team == "Liverpool"
    assert result.away_team == "Bournemouth"
    assert result.home_goals == 4
    assert result.away_goals == 2
    assert result.outcome == "H"
    assert result.avg_home_odds == 1.3
    assert result.avg_draw_odds == 5.4
    assert result.avg_away_odds == 9.0
    assert result.odds_source == "market_average"


def test_league_codes_from_divisions_normalizes_codes() -> None:
    assert league_codes_from_divisions(["e0", "SP1"]) == ["premier-league", "laliga"]


def test_league_codes_from_divisions_rejects_unknown_codes() -> None:
    with pytest.raises(ValueError, match="unsupported division"):
        league_codes_from_divisions(["ZZ"])


def test_division_code_for_league_falls_back_to_league_code() -> None:
    league = League(
        code="custom-league",
        name="Custom League",
        country="Nowhere",
        tier=1,
        source_ids={},
        active=True,
    )

    assert division_code_for_league(league) == "custom-league"


def test_season_code_from_years_requires_consecutive_years() -> None:
    assert season_code_from_years(2025, 2026) == "2526"
    with pytest.raises(ValueError, match="consecutive"):
        season_code_from_years(2025, 2027)

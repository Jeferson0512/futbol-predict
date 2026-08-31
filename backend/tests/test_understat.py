from __future__ import annotations

from datetime import date

import pandas as pd

from futpredict.ingest.providers.understat import (
    UnderstatMatchXg,
    parse_understat_schedule,
    understat_xg_coverage,
)


def _schedule_frame() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "date": pd.Timestamp("2023-08-11 19:00"),
                "home_team": "Burnley",
                "away_team": "Manchester City",
                "home_xg": 0.31,
                "away_xg": 2.40,
                "is_result": True,
            },
            {
                "date": pd.Timestamp("2023-08-12 12:00"),
                "home_team": "Arsenal",
                "away_team": "Nottingham Forest",
                "home_xg": 2.10,
                "away_xg": 0.50,
                "is_result": True,
            },
            {
                "date": pd.Timestamp("2024-05-19 15:00"),
                "home_team": "Chelsea",
                "away_team": "Fulham",
                "home_xg": float("nan"),
                "away_xg": float("nan"),
                "is_result": False,
            },
        ]
    )


def test_parse_maps_team_names_and_skips_matches_without_xg() -> None:
    records = parse_understat_schedule(
        _schedule_frame(),
        league_code="premier-league",
        season="2324",
    )
    assert len(records) == 2
    away_teams = {record.away_team for record in records}
    # Nombres de Understat mapeados a los de football-data.
    assert "Man City" in away_teams
    assert "Nott'm Forest" in away_teams
    first = records[0]
    assert first.match_date == date(2023, 8, 11)
    assert first.home_team == "Burnley"
    assert first.home_xg == 0.31


def test_coverage_counts_matched_fixtures_and_reports_unmatched() -> None:
    understat = [
        UnderstatMatchXg(
            "premier-league", "2324", date(2023, 8, 11), "Man City", "Burnley", 2.4, 0.3
        ),
        UnderstatMatchXg(
            "premier-league", "2324", date(2023, 8, 12), "Arsenal", "Leeds", 2.1, 0.5
        ),
    ]
    db_fixtures = [("Man City", "Burnley"), ("Arsenal", "Nott'm Forest"), ("Chelsea", "Fulham")]

    coverage = understat_xg_coverage(
        db_fixtures,
        understat,
        league_code="premier-league",
        season="2324",
    )
    assert coverage.db_matches == 3
    assert coverage.understat_matches == 2
    assert coverage.matched == 1  # solo Man City vs Burnley coincide
    assert "Leeds" in coverage.unmatched_understat_teams

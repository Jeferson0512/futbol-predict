from __future__ import annotations

from io import StringIO

import pandas as pd

from futpredict.ingest.providers.football_data_uk import (
    parse_fixtures,
    parse_kickoff,
    parse_matches,
    read_csv_from_text,
    read_fixture_csv_from_text,
)

SAMPLE_CSV = """Div,Date,Time,HomeTeam,AwayTeam,FTHG,FTAG,FTR,AvgH,AvgD,AvgA
E0,15/08/2025,20:00,Liverpool,Bournemouth,4,2,H,1.35,5.10,8.20
E0,16/08/2025,12:30,Aston Villa,Newcastle,0,0,D,2.50,3.30,2.80
"""


def test_read_csv_from_text_normalizes_columns() -> None:
    frame = read_csv_from_text(SAMPLE_CSV)
    assert list(frame[["home_team", "away_team", "home_goals", "away_goals"]].iloc[0]) == [
        "Liverpool",
        "Bournemouth",
        4,
        2,
    ]


def test_parse_matches_returns_ordered_domain_rows() -> None:
    frame = pd.read_csv(StringIO(SAMPLE_CSV))
    matches = parse_matches(frame, season="2526", division="E0")
    assert [match.outcome for match in matches] == ["H", "D"]
    assert matches[0].season == "2526"
    assert matches[0].division == "E0"
    assert matches[0].avg_home_odds == 1.35
    assert matches[0].odds_source == "avg"


def test_parse_matches_falls_back_to_legacy_average_odds() -> None:
    csv = """Div,Date,HomeTeam,AwayTeam,FTHG,FTAG,FTR,BbAvH,BbAvD,BbAvA
E0,15/08/2016,Liverpool,Bournemouth,4,2,H,1.40,4.90,8.00
"""
    matches = parse_matches(pd.read_csv(StringIO(csv)), season="1617", division="E0")
    assert matches[0].avg_home_odds == 1.40
    assert matches[0].avg_draw_odds == 4.90
    assert matches[0].avg_away_odds == 8.00
    assert matches[0].odds_source == "legacy_avg"


def test_parse_matches_prefers_closing_average_odds() -> None:
    csv = """Div,Date,Time,HomeTeam,AwayTeam,FTHG,FTAG,FTR,AvgH,AvgD,AvgA,AvgCH,AvgCD,AvgCA
E0,15/08/2025,20:00,Liverpool,Bournemouth,4,2,H,1.35,5.10,8.20,1.30,5.40,9.00
"""
    matches = parse_matches(pd.read_csv(StringIO(csv)), season="2526", division="E0")
    assert matches[0].avg_home_odds == 1.30
    assert matches[0].avg_draw_odds == 5.40
    assert matches[0].avg_away_odds == 9.00
    assert matches[0].odds_source == "avg_closing"


def test_parse_kickoff_uses_utc() -> None:
    kickoff = parse_kickoff("15/08/2025", "20:00")
    assert kickoff.tzinfo is not None
    assert kickoff.year == 2025


def test_parse_fixtures_reads_weekly_fixture_csv() -> None:
    csv = """Div,Date,Time,HomeTeam,AwayTeam,AvgH,AvgD,AvgA
E0,30/08/2026,14:00,Arsenal,Chelsea,2.10,3.50,3.40
"""
    fixtures = parse_fixtures(read_fixture_csv_from_text(csv), season="2627")

    assert len(fixtures) == 1
    assert fixtures[0].season == "2627"
    assert fixtures[0].division == "E0"
    assert fixtures[0].home_team == "Arsenal"
    assert fixtures[0].avg_home_odds == 2.10
    assert fixtures[0].odds_source == "avg"


def test_parse_fixtures_skips_finished_rows() -> None:
    csv = """Div,Date,Time,HomeTeam,AwayTeam,FTHG,FTAG,FTR,AvgH,AvgD,AvgA
E0,15/08/2026,14:00,Arsenal,Chelsea,2,1,H,2.10,3.50,3.40
E0,30/08/2026,14:00,Liverpool,Everton,,,,1.70,3.90,5.00
"""
    fixtures = parse_fixtures(read_fixture_csv_from_text(csv), season="2627")

    assert [fixture.home_team for fixture in fixtures] == ["Liverpool"]

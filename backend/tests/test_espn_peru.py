from __future__ import annotations

from typing import Any

from futpredict.ingest.providers.espn_peru import parse_espn_events


def _event(
    eid: str,
    date: str,
    home: str,
    away: str,
    home_goals: int | None,
    away_goals: int | None,
    completed: bool,
) -> dict[str, Any]:
    return {
        "id": eid,
        "date": date,
        "competitions": [
            {
                "status": {"type": {"completed": completed}},
                "competitors": [
                    {
                        "homeAway": "home",
                        "team": {"displayName": home},
                        "score": None if home_goals is None else str(home_goals),
                    },
                    {
                        "homeAway": "away",
                        "team": {"displayName": away},
                        "score": None if away_goals is None else str(away_goals),
                    },
                ],
            }
        ],
    }


def test_parse_events_reads_results_and_dedupes() -> None:
    events = [
        _event("1", "2023-08-15T18:00Z", "Sporting Cristal", "Alianza Lima", 2, 1, True),
        _event("2", "2023-08-16T20:00Z", "Melgar", "Cienciano del Cusco", None, None, False),
        _event("1", "2023-08-15T18:00Z", "Sporting Cristal", "Alianza Lima", 2, 1, True),
    ]
    matches = parse_espn_events(events, season="2023")
    by_id = {match.espn_id: match for match in matches}

    assert len(matches) == 2  # el duplicado se colapsa
    assert by_id["1"].home_team == "Sporting Cristal"
    assert by_id["1"].season == "2023"
    assert by_id["1"].outcome == "H"
    assert by_id["1"].completed is True
    # Partido programado: sin marcador ni resultado.
    assert by_id["2"].completed is False
    assert by_id["2"].home_goals is None
    assert by_id["2"].outcome is None


def test_parse_events_orders_by_kickoff() -> None:
    events = [
        _event("b", "2023-08-16T20:00Z", "Melgar", "UTC", 1, 1, True),
        _event("a", "2023-08-15T18:00Z", "Cristal", "Alianza", 0, 2, True),
    ]
    matches = parse_espn_events(events, season="2023")
    assert [match.espn_id for match in matches] == ["a", "b"]
    assert matches[0].outcome == "A"

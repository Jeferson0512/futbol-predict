from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

Outcome = str


@dataclass(frozen=True)
class MatchResult:
    kickoff_utc: datetime
    season: str
    division: str
    home_team: str
    away_team: str
    home_goals: int
    away_goals: int
    outcome: Outcome
    avg_home_odds: float | None = None
    avg_draw_odds: float | None = None
    avg_away_odds: float | None = None
    odds_source: str | None = None
    match_id: int | None = None


def result_from_goals(home_goals: int, away_goals: int) -> Outcome:
    if home_goals > away_goals:
        return "H"
    if home_goals == away_goals:
        return "D"
    return "A"

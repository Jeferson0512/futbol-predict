from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class Fixture:
    kickoff_utc: datetime
    season: str
    division: str
    home_team: str
    away_team: str
    status: str = "scheduled"
    avg_home_odds: float | None = None
    avg_draw_odds: float | None = None
    avg_away_odds: float | None = None
    odds_source: str | None = None
    match_id: int | None = None

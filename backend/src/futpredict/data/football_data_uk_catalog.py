from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class Division:
    code: str
    league_code: str
    name: str
    country: str


BIG_FIVE_DIVISIONS: tuple[Division, ...] = (
    Division(code="E0", league_code="premier-league", name="Premier League", country="England"),
    Division(code="SP1", league_code="laliga", name="LaLiga", country="Spain"),
    Division(code="I1", league_code="serie-a", name="Serie A", country="Italy"),
    Division(code="D1", league_code="bundesliga", name="Bundesliga", country="Germany"),
    Division(code="F1", league_code="ligue-1", name="Ligue 1", country="France"),
)

# Ligas fuera de football-data.co.uk (Fase 8). No entran en big_five_division_codes.
EXTRA_DIVISIONS: tuple[Division, ...] = (
    Division(code="PER1", league_code="liga1-peru", name="Liga 1 Peru", country="Peru"),
)

ALL_DIVISIONS: tuple[Division, ...] = (*BIG_FIVE_DIVISIONS, *EXTRA_DIVISIONS)
DIVISIONS_BY_CODE = {division.code: division for division in ALL_DIVISIONS}
DIVISION_BY_LEAGUE_CODE = {division.league_code: division for division in ALL_DIVISIONS}
DEFAULT_BIG_FIVE_START_SEASON = "1617"
DEFAULT_BIG_FIVE_END_SEASON = "2526"


def division_for_league_code(league_code: str) -> str | None:
    division = DIVISION_BY_LEAGUE_CODE.get(league_code)
    return division.code if division is not None else None


def normalize_season_code(season: str) -> str:
    normalized = season.strip()
    if len(normalized) != 4 or not normalized.isdigit():
        msg = "season must use football-data.co.uk format, for example 2526"
        raise ValueError(msg)
    return normalized


def season_range(start: str, end: str) -> list[str]:
    start_code = normalize_season_code(start)
    end_code = normalize_season_code(end)
    start_year = int(start_code[:2])
    end_year = int(end_code[:2])
    if end_year < start_year:
        msg = "end season must be greater than or equal to start season"
        raise ValueError(msg)
    return [f"{year:02d}{year + 1:02d}" for year in range(start_year, end_year + 1)]


def season_years(season: str) -> tuple[int, int]:
    season_code = normalize_season_code(season)
    start_suffix = int(season_code[:2])
    start_year = 1900 + start_suffix if start_suffix >= 70 else 2000 + start_suffix
    return start_year, start_year + 1


def current_season_code(today: date | None = None) -> str:
    current = today if today is not None else date.today()
    start_year = current.year if current.month >= 7 else current.year - 1
    return f"{start_year % 100:02d}{(start_year + 1) % 100:02d}"


def big_five_division_codes() -> list[str]:
    return [division.code for division in BIG_FIVE_DIVISIONS]

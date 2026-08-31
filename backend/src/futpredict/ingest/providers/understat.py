"""Adaptador de xG desde Understat via soccerdata.

Trae el calendario con expected-goals por partido y lo normaliza a registros
propios, mapeando los nombres de equipo de Understat a los de football-data.co.uk
(la fuente base). Incluye una funcion de cobertura para validar el mapeo antes
de construir features de xG.
"""

from __future__ import annotations

import unicodedata
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd

# Codigo de liga propio -> nombre de liga de soccerdata/Understat.
UNDERSTAT_LEAGUE_BY_CODE: dict[str, str] = {
    "premier-league": "ENG-Premier League",
    "laliga": "ESP-La Liga",
    "serie-a": "ITA-Serie A",
    "bundesliga": "GER-Bundesliga",
    "ligue-1": "FRA-Ligue 1",
}

# Nombre de Understat -> nombre football-data (el que guardamos como canonico).
# Se amplia segun lo que reporte el comando de cobertura.
UNDERSTAT_TEAM_REPLACEMENTS: dict[str, str] = {
    "Manchester United": "Man United",
    "Manchester City": "Man City",
    "Newcastle United": "Newcastle",
    "Wolverhampton Wanderers": "Wolves",
    "Nottingham Forest": "Nott'm Forest",
    "Sheffield United": "Sheffield United",
    "Paris Saint Germain": "Paris SG",
    "Bayern Munich": "Bayern Munich",
    "Borussia Dortmund": "Dortmund",
    "Borussia M.Gladbach": "M'gladbach",
    "Bayer Leverkusen": "Leverkusen",
    "RasenBallsport Leipzig": "RB Leipzig",
    "Athletic Club": "Ath Bilbao",
    "Atletico Madrid": "Ath Madrid",
    "Real Betis": "Betis",
    "Real Sociedad": "Sociedad",
    "Espanyol": "Espanol",
    "Celta Vigo": "Celta",
    "Rayo Vallecano": "Vallecano",
    "Internazionale": "Inter",
    "AC Milan": "Milan",
    "Hellas Verona": "Verona",
    "Eintracht Frankfurt": "Ein Frankfurt",
    "FC Cologne": "FC Koln",
    "FC Heidenheim": "Heidenheim",
    "Mainz 05": "Mainz",
    "VfB Stuttgart": "Stuttgart",
    "Clermont Foot": "Clermont",
}


@dataclass(frozen=True)
class UnderstatMatchXg:
    league_code: str
    season: str
    match_date: date
    home_team: str
    away_team: str
    home_xg: float
    away_xg: float


@dataclass(frozen=True)
class UnderstatCoverage:
    league_code: str
    season: str
    understat_matches: int
    db_matches: int
    matched: int
    unmatched_understat_teams: list[str]

    @property
    def coverage_ratio(self) -> float:
        return 0.0 if self.db_matches == 0 else self.matched / self.db_matches


def normalize_team(name: str) -> str:
    text = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    return "".join(char for char in text.lower() if char.isalnum())


def canonical_team(understat_name: str) -> str:
    return UNDERSTAT_TEAM_REPLACEMENTS.get(understat_name, understat_name)


def parse_understat_schedule(
    frame: pd.DataFrame,
    *,
    league_code: str,
    season: str,
) -> list[UnderstatMatchXg]:
    records: list[UnderstatMatchXg] = []
    flat = frame.reset_index()
    for row in flat.to_dict("records"):
        if not _has_xg(row):
            continue
        records.append(
            UnderstatMatchXg(
                league_code=league_code,
                season=season,
                match_date=pd.Timestamp(row["date"]).date(),
                home_team=canonical_team(str(row["home_team"])),
                away_team=canonical_team(str(row["away_team"])),
                home_xg=float(row["home_xg"]),
                away_xg=float(row["away_xg"]),
            )
        )
    return records


def fetch_understat_xg(
    *,
    league_code: str,
    season: str,
    cache_dir: Path | None = None,
) -> list[UnderstatMatchXg]:
    import soccerdata

    try:
        league = UNDERSTAT_LEAGUE_BY_CODE[league_code]
    except KeyError as exc:
        msg = f"no Understat league mapping for {league_code!r}"
        raise ValueError(msg) from exc

    reader = soccerdata.Understat(
        leagues=league,
        seasons=season,
        data_dir=cache_dir if cache_dir is not None else None,
    )
    frame = reader.read_schedule()
    return parse_understat_schedule(frame, league_code=league_code, season=season)


def understat_xg_coverage(
    db_fixtures: Sequence[tuple[str, str]],
    understat_matches: Iterable[UnderstatMatchXg],
    *,
    league_code: str,
    season: str,
) -> UnderstatCoverage:
    understat_list = list(understat_matches)
    understat_by_key = {
        (normalize_team(match.home_team), normalize_team(match.away_team)): match
        for match in understat_list
    }
    matched = sum(
        1
        for home, away in db_fixtures
        if (normalize_team(home), normalize_team(away)) in understat_by_key
    )
    our_team_keys = {normalize_team(home) for home, _away in db_fixtures}
    our_team_keys |= {normalize_team(away) for _home, away in db_fixtures}
    unmatched = sorted(
        {
            team
            for match in understat_list
            for team in (match.home_team, match.away_team)
            if normalize_team(team) not in our_team_keys
        }
    )
    return UnderstatCoverage(
        league_code=league_code,
        season=season,
        understat_matches=len(understat_list),
        db_matches=len(db_fixtures),
        matched=matched,
        unmatched_understat_teams=unmatched,
    )


def _has_xg(row: dict[Any, Any]) -> bool:
    if not bool(row.get("is_result", True)):
        return False
    return not (pd.isna(row.get("home_xg")) or pd.isna(row.get("away_xg")))

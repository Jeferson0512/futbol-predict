"""Carga de la temporada europea en curso desde ESPN.

football-data.co.uk publica los Big-5 con retraso; ESPN ya tiene la temporada
2026/27. Este loader trae esos partidos (resultados + fixtures) y los enlaza a
los equipos football-data ya existentes (mapeo de nombres ESPN -> football-data),
para no duplicar equipos ni romper el Elo historico. Solo carga la temporada
nueva (no pisa lo que ya existe).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import cast

from sqlalchemy import Table, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from futpredict.data.db_matches import league_codes_from_divisions
from futpredict.db.models import League, Match, Season, Team
from futpredict.ingest.providers.espn_peru import (
    ESPN_DIVISION_SLUGS,
    EspnPeruMatch,
    fetch_espn_season,
)
from futpredict.ingest.providers.understat import normalize_team

# Nombre de ESPN -> nombre football-data (el canonico de nuestros equipos).
# Se amplia con lo que reporte `unmatched`.
ESPN_EUROPE_TEAM_REPLACEMENTS: dict[str, str] = {
    "AFC Bournemouth": "Bournemouth",
    "Brighton & Hove Albion": "Brighton",
    "Coventry City": "Coventry",
    "Hull City": "Hull",
    "Ipswich Town": "Ipswich",
    "Leeds United": "Leeds",
    "Leicester City": "Leicester",
    "Manchester City": "Man City",
    "Manchester United": "Man United",
    "Newcastle United": "Newcastle",
    "Nottingham Forest": "Nott'm Forest",
    "Tottenham Hotspur": "Tottenham",
    "West Ham United": "West Ham",
    "Wolverhampton Wanderers": "Wolves",
    # LaLiga
    "Athletic Club": "Ath Bilbao",
    "Atlético Madrid": "Ath Madrid",
    "Celta Vigo": "Celta",
    "Deportivo": "La Coruna",
    "Espanyol": "Espanol",
    "Racing Santander": "Santander",
    "Rayo Vallecano": "Vallecano",
    "Real Betis": "Betis",
    "Real Sociedad": "Sociedad",
    # Serie A
    "AC Milan": "Milan",
    "AS Roma": "Roma",
    "Internazionale": "Inter",
    "Hellas Verona": "Verona",
    # Bundesliga
    "1. FC Union Berlin": "Union Berlin",
    "Bayer Leverkusen": "Leverkusen",
    "Borussia Dortmund": "Dortmund",
    "Borussia Mönchengladbach": "M'gladbach",
    "Eintracht Frankfurt": "Ein Frankfurt",
    "FC Augsburg": "Augsburg",
    "FC Cologne": "FC Koln",
    "Hamburg SV": "Hamburg",
    "SC Freiburg": "Freiburg",
    "SC Paderborn 07": "Paderborn",
    "SV Elversberg": "Elversberg",
    "TSG Hoffenheim": "Hoffenheim",
    "VfB Stuttgart": "Stuttgart",
    # Ligue 1
    "AJ Auxerre": "Auxerre",
    "AS Monaco": "Monaco",
    "Le Havre AC": "Le Havre",
    "Paris Saint-Germain": "Paris SG",
    "Stade Rennais": "Rennes",
}


@dataclass(frozen=True)
class EspnEuropeLoadSummary:
    division: str
    season: str
    fetched: int
    loaded: int
    finished: int
    unmatched_teams: list[str]


def load_espn_europe_season(
    session: Session,
    division: str,
    *,
    season_start_year: int,
    commit: bool = True,
) -> EspnEuropeLoadSummary:
    slug = ESPN_DIVISION_SLUGS[division]
    league_codes = league_codes_from_divisions([division])
    league = session.execute(
        select(League).where(League.code == league_codes[0])
    ).scalar_one_or_none()
    if league is None:
        msg = f"la liga {division} no existe; carga football-data primero"
        raise ValueError(msg)

    teams_by_norm: dict[str, int] = {}
    for team_id, name in session.execute(
        select(Team.id, Team.name).where(Team.league_id == league.id)
    ).all():
        teams_by_norm[normalize_team(cast(str, name))] = cast(int, team_id)

    season_code = f"{season_start_year % 100:02d}{(season_start_year + 1) % 100:02d}"
    season_id = _upsert_season(session, league.id, season_start_year, season_start_year + 1)

    window_start = datetime(season_start_year, 8, 1, tzinfo=UTC)
    fetched = [
        match
        for match in (
            *fetch_espn_season(slug, season_start_year, season=season_code),
            *fetch_espn_season(slug, season_start_year + 1, season=season_code),
        )
        if match.kickoff_utc >= window_start
    ]

    unmatched: set[str] = set()
    loaded = 0
    finished = 0
    timestamp = datetime.now(UTC)
    for match in fetched:
        home_id = _lookup_team(teams_by_norm, match.home_team, unmatched)
        away_id = _lookup_team(teams_by_norm, match.away_team, unmatched)
        if home_id is None or away_id is None or home_id == away_id:
            continue
        _upsert_match(session, league.id, season_id, home_id, away_id, match, timestamp)
        loaded += 1
        if match.completed:
            finished += 1

    if commit:
        session.commit()

    return EspnEuropeLoadSummary(
        division=division,
        season=season_code,
        fetched=len(fetched),
        loaded=loaded,
        finished=finished,
        unmatched_teams=sorted(unmatched),
    )


def _lookup_team(
    teams_by_norm: dict[str, int],
    espn_name: str,
    unmatched: set[str],
) -> int | None:
    canonical = ESPN_EUROPE_TEAM_REPLACEMENTS.get(espn_name, espn_name)
    team_id = teams_by_norm.get(normalize_team(canonical))
    if team_id is None:
        unmatched.add(espn_name)
    return team_id


def _upsert_season(session: Session, league_id: int, year_start: int, year_end: int) -> int:
    table = cast(Table, Season.__table__)
    statement = (
        insert(table)
        .values(league_id=league_id, year_start=year_start, year_end=year_end)
        .on_conflict_do_nothing(constraint="uq_season_league_years")
        .returning(table.c.id)
    )
    created = session.execute(statement).scalar_one_or_none()
    if created is not None:
        return int(created)
    existing = session.execute(
        select(Season.id).where(
            Season.league_id == league_id,
            Season.year_start == year_start,
            Season.year_end == year_end,
        )
    ).scalar_one()
    return int(existing)


def _upsert_match(
    session: Session,
    league_id: int,
    season_id: int,
    home_team_id: int,
    away_team_id: int,
    match: EspnPeruMatch,
    ingested_at: datetime,
) -> None:
    table = cast(Table, Match.__table__)
    status = "finished" if match.completed else "scheduled"
    base = insert(table).values(
        league_id=league_id,
        season_id=season_id,
        home_team_id=home_team_id,
        away_team_id=away_team_id,
        kickoff_utc=match.kickoff_utc,
        status=status,
        home_goals=match.home_goals,
        away_goals=match.away_goals,
        home_ht=None,
        away_ht=None,
        home_xg=None,
        away_xg=None,
        shots={},
        shots_on_target={},
        corners={},
        cards={},
        raw={"espn_id": match.espn_id},
        source="espn",
        ingested_at=ingested_at,
    )
    statement = base.on_conflict_do_update(
        constraint="uq_match_fixture_identity",
        set_={
            "status": base.excluded.status,
            "home_goals": base.excluded.home_goals,
            "away_goals": base.excluded.away_goals,
        },
    )
    session.execute(statement)


def load_all_espn_europe(
    session: Session,
    *,
    season_start_year: int,
    divisions: Sequence[str] = ("E0", "SP1", "I1", "D1", "F1"),
    commit: bool = True,
) -> list[EspnEuropeLoadSummary]:
    return [
        load_espn_europe_season(
            session,
            division,
            season_start_year=season_start_year,
            commit=commit,
        )
        for division in divisions
    ]

"""Carga generica de una liga de ESPN (ano calendario) a PostgreSQL.

Generaliza el patron de `db_peru`: upserts directos de liga, temporadas (por ano
calendario), equipos y partidos desde `EspnPeruMatch`, sin pasar por el pipeline
normalizado de football-data. Idempotente: al re-cargar, actualiza estado y
marcador de los partidos ya jugados. Sirve para Brasil, Argentina y cualquier
otra liga de ESPN con calendario por ano.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import cast

from sqlalchemy import Table, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from futpredict.db.models import League, Match, Season, Team
from futpredict.ingest.providers.espn_peru import ESPN_DIVISION_SLUGS, EspnPeruMatch


@dataclass(frozen=True)
class EspnLeagueConfig:
    league_code: str
    name: str
    country: str
    division: str  # codigo propio, p.ej. BRA1

    @property
    def slug(self) -> str:
        return ESPN_DIVISION_SLUGS[self.division]


BRAZIL = EspnLeagueConfig(
    league_code="brasileirao",
    name="Brasileirao Serie A",
    country="Brazil",
    division="BRA1",
)
ARGENTINA = EspnLeagueConfig(
    league_code="liga-argentina",
    name="Liga Profesional Argentina",
    country="Argentina",
    division="ARG1",
)

ESPN_LEAGUES: dict[str, EspnLeagueConfig] = {
    "brazil": BRAZIL,
    "argentina": ARGENTINA,
}


@dataclass(frozen=True)
class EspnLeagueLoadSummary:
    league_code: str
    seasons: int
    teams: int
    matches: int
    finished: int
    scheduled: int


def load_espn_league_matches(
    session: Session,
    config: EspnLeagueConfig,
    matches: Sequence[EspnPeruMatch],
    *,
    ingested_at: datetime | None = None,
    commit: bool = True,
) -> EspnLeagueLoadSummary:
    timestamp = ingested_at if ingested_at is not None else datetime.now(UTC)
    league_id = _upsert_league(session, config)
    season_ids: dict[str, int] = {}
    team_ids: dict[str, int] = {}
    finished = 0

    for match in matches:
        if match.season not in season_ids:
            season_ids[match.season] = _upsert_season(session, league_id, int(match.season))
        for name in (match.home_team, match.away_team):
            if name not in team_ids:
                team_ids[name] = _upsert_team(session, league_id, name)
        _upsert_match(
            session,
            league_id=league_id,
            season_id=season_ids[match.season],
            home_team_id=team_ids[match.home_team],
            away_team_id=team_ids[match.away_team],
            match=match,
            ingested_at=timestamp,
        )
        if match.completed:
            finished += 1

    if commit:
        session.commit()

    return EspnLeagueLoadSummary(
        league_code=config.league_code,
        seasons=len(season_ids),
        teams=len(team_ids),
        matches=len(matches),
        finished=finished,
        scheduled=len(matches) - finished,
    )


def _upsert_league(session: Session, config: EspnLeagueConfig) -> int:
    table = cast(Table, League.__table__)
    statement = (
        insert(table)
        .values(
            code=config.league_code,
            name=config.name,
            country=config.country,
            tier=1,
            source_ids={"espn": config.division},
            active=True,
        )
        .on_conflict_do_update(
            index_elements=[table.c.code],
            set_={"name": config.name, "country": config.country},
        )
        .returning(table.c.id)
    )
    return _scalar_int(session.execute(statement).scalar_one())


def _upsert_season(session: Session, league_id: int, year: int) -> int:
    table = cast(Table, Season.__table__)
    statement = (
        insert(table)
        .values(league_id=league_id, year_start=year, year_end=year)
        .on_conflict_do_nothing(constraint="uq_season_league_years")
        .returning(table.c.id)
    )
    created = session.execute(statement).scalar_one_or_none()
    if created is not None:
        return _scalar_int(created)
    existing = session.execute(
        select(Season.id).where(
            Season.league_id == league_id,
            Season.year_start == year,
            Season.year_end == year,
        )
    ).scalar_one()
    return _scalar_int(existing)


def _upsert_team(session: Session, league_id: int, name: str) -> int:
    table = cast(Table, Team.__table__)
    statement = (
        insert(table)
        .values(league_id=league_id, name=name, canonical_name=name, aliases=[], source_ids={})
        .on_conflict_do_nothing(constraint="uq_team_league_canonical")
        .returning(table.c.id)
    )
    created = session.execute(statement).scalar_one_or_none()
    if created is not None:
        return _scalar_int(created)
    existing = session.execute(
        select(Team.id).where(Team.league_id == league_id, Team.canonical_name == name)
    ).scalar_one()
    return _scalar_int(existing)


def _upsert_match(
    session: Session,
    *,
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
            "kickoff_utc": base.excluded.kickoff_utc,
            "home_goals": base.excluded.home_goals,
            "away_goals": base.excluded.away_goals,
        },
        # No pisar un resultado con un fixture sin marcador (ver db_espn_europe).
        where=or_(base.excluded.home_goals.isnot(None), table.c.home_goals.is_(None)),
    )
    session.execute(statement)


def _scalar_int(value: object) -> int:
    if not isinstance(value, int):
        msg = f"expected integer primary key, got {type(value).__name__}"
        raise TypeError(msg)
    return value

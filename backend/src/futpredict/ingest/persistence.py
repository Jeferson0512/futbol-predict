from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import cast

from sqlalchemy import Table
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from futpredict.db.models import League, Match, Odd, Season, Team, TeamAlias
from futpredict.ingest.normalized import (
    SOURCE_NAME,
    LeagueKey,
    MatchKey,
    NormalizedBatch,
    NormalizedBatchValidation,
    OddRecord,
    SeasonKey,
    TeamKey,
    canonical_team_name,
    validate_normalized_batch,
)


@dataclass(frozen=True)
class PersistenceSummary:
    leagues: int
    seasons: int
    teams: int
    team_aliases: int
    matches: int
    odds: int


class NormalizedBatchIntegrityError(ValueError):
    """Raised when a staging batch is not safe to persist."""


def load_normalized_batch(
    session: Session,
    batch: NormalizedBatch,
    *,
    ingested_at: datetime | None = None,
    commit: bool = True,
) -> PersistenceSummary:
    validation = validate_normalized_batch(batch)
    if validation.has_errors:
        raise NormalizedBatchIntegrityError(_format_validation_errors(validation))

    timestamp = ingested_at if ingested_at is not None else datetime.now(UTC)
    league_ids = _upsert_leagues(session, batch)
    season_ids = _upsert_seasons(session, batch, league_ids)
    team_ids = _upsert_teams(session, batch, league_ids)
    team_alias_count = _upsert_team_aliases(session, batch, league_ids, team_ids, timestamp)
    match_ids = _upsert_matches(session, batch, league_ids, season_ids, team_ids, timestamp)
    _upsert_odds(session, batch.odds, match_ids)

    if commit:
        session.commit()

    return PersistenceSummary(
        leagues=len(batch.leagues),
        seasons=len(batch.seasons),
        teams=len(batch.teams),
        team_aliases=team_alias_count,
        matches=len(batch.matches),
        odds=len(batch.odds),
    )


def _upsert_leagues(session: Session, batch: NormalizedBatch) -> dict[LeagueKey, int]:
    league_ids: dict[LeagueKey, int] = {}
    table = cast(Table, League.__table__)
    for league in batch.leagues:
        base = insert(table).values(
            code=league.code,
            name=league.name,
            country=league.country,
            tier=league.tier,
            source_ids=dict(league.source_ids),
            active=True,
        )
        statement = base.on_conflict_do_update(
            index_elements=[table.c.code],
            set_={
                "name": base.excluded.name,
                "country": base.excluded.country,
                "tier": base.excluded.tier,
                "source_ids": base.excluded.source_ids,
                "active": True,
            },
        ).returning(table.c.id)
        league_ids[league.key] = _scalar_int(session.execute(statement).scalar_one())
    return league_ids


def _upsert_seasons(
    session: Session,
    batch: NormalizedBatch,
    league_ids: Mapping[LeagueKey, int],
) -> dict[SeasonKey, int]:
    season_ids: dict[SeasonKey, int] = {}
    table = cast(Table, Season.__table__)
    for season in batch.seasons:
        base = insert(table).values(
            league_id=league_ids[season.league_code],
            year_start=season.year_start,
            year_end=season.year_end,
        )
        statement = base.on_conflict_do_update(
            constraint="uq_season_league_years",
            set_={
                "year_start": base.excluded.year_start,
                "year_end": base.excluded.year_end,
            },
        ).returning(table.c.id)
        season_ids[season.key] = _scalar_int(session.execute(statement).scalar_one())
    return season_ids


def _upsert_teams(
    session: Session,
    batch: NormalizedBatch,
    league_ids: Mapping[LeagueKey, int],
) -> dict[TeamKey, int]:
    team_ids: dict[TeamKey, int] = {}
    table = cast(Table, Team.__table__)
    for team in batch.teams:
        base = insert(table).values(
            league_id=league_ids[team.league_code],
            name=team.name,
            canonical_name=team.canonical_name,
            aliases=list(team.aliases),
            source_ids=dict(team.source_ids),
        )
        statement = base.on_conflict_do_update(
            constraint="uq_team_league_canonical",
            set_={
                "name": base.excluded.name,
                "aliases": base.excluded.aliases,
                "source_ids": base.excluded.source_ids,
            },
        ).returning(table.c.id)
        team_ids[team.key] = _scalar_int(session.execute(statement).scalar_one())
    return team_ids


def _upsert_team_aliases(
    session: Session,
    batch: NormalizedBatch,
    league_ids: Mapping[LeagueKey, int],
    team_ids: Mapping[TeamKey, int],
    created_at: datetime,
) -> int:
    count = 0
    table = cast(Table, TeamAlias.__table__)
    for team in batch.teams:
        seen_aliases: set[str] = set()
        for index, alias in enumerate(team.aliases):
            canonical_alias = canonical_team_name(alias)
            if canonical_alias in seen_aliases:
                continue
            seen_aliases.add(canonical_alias)
            base = insert(table).values(
                league_id=league_ids[team.league_code],
                team_id=team_ids[team.key],
                source=SOURCE_NAME,
                alias=alias,
                canonical_alias=canonical_alias,
                is_primary=index == 0,
                active=True,
                created_at=created_at,
            )
            statement = base.on_conflict_do_update(
                constraint="uq_team_alias_league_source_canonical",
                set_={
                    "team_id": base.excluded.team_id,
                    "alias": base.excluded.alias,
                    "is_primary": base.excluded.is_primary,
                    "active": True,
                },
            )
            session.execute(statement)
            count += 1
    return count


def _upsert_matches(
    session: Session,
    batch: NormalizedBatch,
    league_ids: Mapping[LeagueKey, int],
    season_ids: Mapping[SeasonKey, int],
    team_ids: Mapping[TeamKey, int],
    ingested_at: datetime,
) -> dict[MatchKey, int]:
    match_ids: dict[MatchKey, int] = {}
    table = cast(Table, Match.__table__)
    for match in batch.matches:
        base = insert(table).values(
            league_id=league_ids[match.league_code],
            season_id=season_ids[match.season_key],
            home_team_id=team_ids[match.home_team_key],
            away_team_id=team_ids[match.away_team_key],
            kickoff_utc=match.kickoff_utc,
            status=match.status,
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
            raw=dict(match.raw),
            source=match.source,
            ingested_at=ingested_at,
        )
        statement = base.on_conflict_do_update(
            constraint="uq_match_fixture_identity",
            set_={
                "status": base.excluded.status,
                "home_goals": base.excluded.home_goals,
                "away_goals": base.excluded.away_goals,
                "home_ht": base.excluded.home_ht,
                "away_ht": base.excluded.away_ht,
                "home_xg": base.excluded.home_xg,
                "away_xg": base.excluded.away_xg,
                "shots": base.excluded.shots,
                "shots_on_target": base.excluded.shots_on_target,
                "corners": base.excluded.corners,
                "cards": base.excluded.cards,
                "raw": base.excluded.raw,
                "source": base.excluded.source,
                "ingested_at": base.excluded.ingested_at,
            },
        ).returning(table.c.id)
        match_ids[match.key] = _scalar_int(session.execute(statement).scalar_one())
    return match_ids


def _upsert_odds(
    session: Session,
    odds: tuple[OddRecord, ...],
    match_ids: Mapping[MatchKey, int],
) -> None:
    table = cast(Table, Odd.__table__)
    for odd in odds:
        base = insert(table).values(
            match_id=match_ids[odd.match_key],
            bookmaker=odd.bookmaker,
            market=odd.market,
            odd_home=odd.odd_home,
            odd_draw=odd.odd_draw,
            odd_away=odd.odd_away,
            captured_at=odd.captured_at,
            is_closing=odd.is_closing,
        )
        statement = base.on_conflict_do_update(
            constraint="uq_odd_match_bookmaker_market",
            set_={
                "odd_home": base.excluded.odd_home,
                "odd_draw": base.excluded.odd_draw,
                "odd_away": base.excluded.odd_away,
                "captured_at": base.excluded.captured_at,
                "is_closing": base.excluded.is_closing,
            },
        )
        session.execute(statement)


def _format_validation_errors(validation: NormalizedBatchValidation) -> str:
    parts: list[str] = []
    if validation.duplicate_league_keys:
        parts.append(f"duplicate leagues={len(validation.duplicate_league_keys)}")
    if validation.duplicate_season_keys:
        parts.append(f"duplicate seasons={len(validation.duplicate_season_keys)}")
    if validation.duplicate_team_keys:
        parts.append(f"duplicate teams={len(validation.duplicate_team_keys)}")
    if validation.duplicate_match_keys:
        parts.append(f"duplicate matches={len(validation.duplicate_match_keys)}")
    if validation.duplicate_odd_keys:
        parts.append(f"duplicate odds={len(validation.duplicate_odd_keys)}")
    if validation.orphan_odd_match_keys:
        parts.append(f"orphan odds={len(validation.orphan_odd_match_keys)}")
    return "normalized batch is not safe to persist: " + ", ".join(parts)


def _scalar_int(value: object) -> int:
    if not isinstance(value, int):
        msg = f"expected integer primary key, got {type(value).__name__}"
        raise TypeError(msg)
    return value

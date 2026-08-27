from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import cast

from sqlalchemy import Table, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from futpredict.data.db_matches import league_codes_from_divisions
from futpredict.data.football_data_uk_catalog import season_range, season_years
from futpredict.db.models import EloRating, League, Match, Season
from futpredict.models.elo import EloConfig, update_elo

ELO_RATING_SYSTEM = "elo_simple_v1"
INITIAL_ELO_RATING = 1500.0


@dataclass(frozen=True)
class EloMatch:
    match_id: int
    league_code: str
    kickoff_utc: datetime
    home_team_id: int
    away_team_id: int
    home_goals: int
    away_goals: int


@dataclass(frozen=True)
class EloRatingSnapshot:
    team_id: int
    match_id: int
    rating_before: Decimal
    rating_after: Decimal


@dataclass(frozen=True)
class EloPersistenceSummary:
    rating_system: str
    matches: int
    ratings: int


def load_elo_matches_from_db(
    session: Session,
    *,
    start_season: str,
    end_season: str,
    division_codes: Sequence[str] | None = None,
) -> list[EloMatch]:
    seasons = season_range(start_season, end_season)
    start_year, _start_end_year = season_years(seasons[0])
    _end_start_year, end_year = season_years(seasons[-1])
    league_codes = league_codes_from_divisions(division_codes)
    if division_codes is not None and not league_codes:
        return []

    statement = (
        select(
            Match.id,
            League.code,
            Match.kickoff_utc,
            Match.home_team_id,
            Match.away_team_id,
            Match.home_goals,
            Match.away_goals,
        )
        .join(League, Match.league_id == League.id)
        .join(Season, Match.season_id == Season.id)
        .where(
            Season.year_start >= start_year,
            Season.year_end <= end_year,
            Match.status == "finished",
            Match.home_goals.is_not(None),
            Match.away_goals.is_not(None),
        )
        .order_by(Match.kickoff_utc, Match.id)
    )
    if league_codes:
        statement = statement.where(League.code.in_(league_codes))

    matches: list[EloMatch] = []
    for row in session.execute(statement):
        matches.append(
            EloMatch(
                match_id=cast(int, row[0]),
                league_code=cast(str, row[1]),
                kickoff_utc=cast(datetime, row[2]),
                home_team_id=cast(int, row[3]),
                away_team_id=cast(int, row[4]),
                home_goals=_required_score(cast(int | None, row[5]), "home_goals"),
                away_goals=_required_score(cast(int | None, row[6]), "away_goals"),
            )
        )
    return matches


def build_elo_rating_snapshots(
    matches: Sequence[EloMatch],
    *,
    config: EloConfig | None = None,
    initial_rating: float = INITIAL_ELO_RATING,
) -> list[EloRatingSnapshot]:
    cfg = config or EloConfig()
    ratings: dict[tuple[str, int], float] = {}
    snapshots: list[EloRatingSnapshot] = []
    ordered = sorted(matches, key=lambda match: (match.kickoff_utc, match.match_id))

    for match in ordered:
        home_key = (match.league_code, match.home_team_id)
        away_key = (match.league_code, match.away_team_id)
        home_before = ratings.get(home_key, initial_rating)
        away_before = ratings.get(away_key, initial_rating)
        home_after, away_after = update_elo(
            home_before,
            away_before,
            match.home_goals,
            match.away_goals,
            cfg,
        )

        snapshots.append(
            EloRatingSnapshot(
                team_id=match.home_team_id,
                match_id=match.match_id,
                rating_before=_rating_decimal(home_before),
                rating_after=_rating_decimal(home_after),
            )
        )
        snapshots.append(
            EloRatingSnapshot(
                team_id=match.away_team_id,
                match_id=match.match_id,
                rating_before=_rating_decimal(away_before),
                rating_after=_rating_decimal(away_after),
            )
        )

        ratings[home_key] = home_after
        ratings[away_key] = away_after

    return snapshots


def upsert_elo_rating_snapshots(
    session: Session,
    snapshots: Sequence[EloRatingSnapshot],
    *,
    rating_system: str = ELO_RATING_SYSTEM,
    computed_at: datetime | None = None,
    commit: bool = True,
) -> EloPersistenceSummary:
    timestamp = computed_at if computed_at is not None else datetime.now(UTC)
    table = cast(Table, EloRating.__table__)
    for snapshot in snapshots:
        base = insert(table).values(
            team_id=snapshot.team_id,
            match_id=snapshot.match_id,
            rating_before=snapshot.rating_before,
            rating_after=snapshot.rating_after,
            computed_at=timestamp,
        )
        statement = base.on_conflict_do_update(
            constraint="uq_elo_team_match",
            set_={
                "rating_before": base.excluded.rating_before,
                "rating_after": base.excluded.rating_after,
                "computed_at": base.excluded.computed_at,
            },
        )
        session.execute(statement)

    if commit:
        session.commit()

    return EloPersistenceSummary(
        rating_system=rating_system,
        matches=len({snapshot.match_id for snapshot in snapshots}),
        ratings=len(snapshots),
    )


def _rating_decimal(value: float) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.001"))


def _required_score(value: int | None, field_name: str) -> int:
    if value is None:
        msg = f"finished match is missing {field_name}"
        raise ValueError(msg)
    return value

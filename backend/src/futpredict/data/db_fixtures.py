from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import cast

from sqlalchemy import and_, case, or_, select
from sqlalchemy.orm import Session, aliased

from futpredict.data.db_matches import (
    division_code_for_league,
    league_codes_from_divisions,
    season_code_from_years,
)
from futpredict.db.models import League, Match, Odd, Season, Team
from futpredict.domain.fixtures import Fixture
from futpredict.ingest.normalized import MARKET_1X2


def load_upcoming_fixtures_from_db(
    session: Session,
    *,
    start_at: datetime | None = None,
    end_at: datetime | None = None,
    division_codes: Sequence[str] | None = None,
    limit: int = 50,
) -> list[Fixture]:
    lower_bound = start_at if start_at is not None else datetime.now(UTC)
    upper_bound = end_at
    league_codes = league_codes_from_divisions(division_codes)
    if division_codes is not None and not league_codes:
        return []

    home_team = aliased(Team)
    away_team = aliased(Team)
    odds_preference = case((Odd.bookmaker == "market_average", 0), else_=1)
    statement = (
        select(Match, League, Season, home_team.name, away_team.name, Odd)
        .join(League, Match.league_id == League.id)
        .join(Season, Match.season_id == Season.id)
        .join(home_team, Match.home_team_id == home_team.id)
        .join(away_team, Match.away_team_id == away_team.id)
        .outerjoin(Odd, and_(Odd.match_id == Match.id, Odd.market == MARKET_1X2))
        .where(
            Match.kickoff_utc >= lower_bound,
            or_(
                Match.status != "finished",
                Match.home_goals.is_(None),
                Match.away_goals.is_(None),
            ),
        )
        .order_by(Match.kickoff_utc, Match.id, odds_preference, Odd.is_closing.desc(), Odd.id)
    )
    if upper_bound is not None:
        statement = statement.where(Match.kickoff_utc < upper_bound)
    if league_codes:
        statement = statement.where(League.code.in_(league_codes))

    fixtures: list[Fixture] = []
    seen_match_ids: set[int] = set()
    for row in session.execute(statement):
        match = cast(Match, row[0])
        if match.id in seen_match_ids:
            continue
        seen_match_ids.add(match.id)
        fixtures.append(
            _fixture_from_db_row(
                match=match,
                league=cast(League, row[1]),
                season=cast(Season, row[2]),
                home_team_name=cast(str, row[3]),
                away_team_name=cast(str, row[4]),
                odd=cast(Odd | None, row[5]),
            )
        )
        if len(fixtures) >= limit:
            break

    return fixtures


def load_next_fixtures_from_db(
    session: Session,
    *,
    days: int = 14,
    division_codes: Sequence[str] | None = None,
    limit: int = 50,
) -> list[Fixture]:
    start_at = datetime.now(UTC)
    return load_upcoming_fixtures_from_db(
        session,
        start_at=start_at,
        end_at=start_at + timedelta(days=days),
        division_codes=division_codes,
        limit=limit,
    )


def _fixture_from_db_row(
    *,
    match: Match,
    league: League,
    season: Season,
    home_team_name: str,
    away_team_name: str,
    odd: Odd | None,
) -> Fixture:
    home_odds, draw_odds, away_odds, odds_source = _odds_from_db(odd)
    return Fixture(
        match_id=match.id,
        kickoff_utc=match.kickoff_utc,
        season=season_code_from_years(season.year_start, season.year_end),
        division=division_code_for_league(league),
        home_team=home_team_name,
        away_team=away_team_name,
        status=match.status,
        avg_home_odds=home_odds,
        avg_draw_odds=draw_odds,
        avg_away_odds=away_odds,
        odds_source=odds_source,
    )


def _odds_from_db(odd: Odd | None) -> tuple[float | None, float | None, float | None, str | None]:
    if odd is None:
        return None, None, None, None
    return (
        _decimal_to_float(odd.odd_home),
        _decimal_to_float(odd.odd_draw),
        _decimal_to_float(odd.odd_away),
        odd.bookmaker,
    )


def _decimal_to_float(value: Decimal) -> float:
    return float(value)

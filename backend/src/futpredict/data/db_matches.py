from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from decimal import Decimal
from typing import cast

from sqlalchemy import and_, case, select
from sqlalchemy.orm import Session, aliased

from futpredict.data.football_data_uk_catalog import (
    DIVISIONS_BY_CODE,
    normalize_season_code,
    season_range,
    season_years,
)
from futpredict.db.models import League, Match, Odd, Season, Team
from futpredict.domain.matches import MatchResult, result_from_goals
from futpredict.ingest.normalized import MARKET_1X2, SOURCE_NAME


def load_match_results_from_db(
    session: Session,
    *,
    start_season: str,
    end_season: str,
    division_codes: Sequence[str] | None = None,
) -> list[MatchResult]:
    seasons = season_range(start_season, end_season)
    start_year, _start_end_year = season_years(seasons[0])
    _end_start_year, end_year = season_years(seasons[-1])
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
            Season.year_start >= start_year,
            Season.year_end <= end_year,
            Match.status == "finished",
            Match.home_goals.is_not(None),
            Match.away_goals.is_not(None),
        )
        .order_by(Match.kickoff_utc, Match.id, odds_preference, Odd.is_closing.desc(), Odd.id)
    )
    if league_codes:
        statement = statement.where(League.code.in_(league_codes))

    results: list[MatchResult] = []
    seen_match_ids: set[int] = set()
    for row in session.execute(statement):
        match = cast(Match, row[0])
        if match.id in seen_match_ids:
            continue
        seen_match_ids.add(match.id)
        results.append(
            match_result_from_db_row(
                match=match,
                league=cast(League, row[1]),
                season=cast(Season, row[2]),
                home_team_name=cast(str, row[3]),
                away_team_name=cast(str, row[4]),
                odd=cast(Odd | None, row[5]),
            )
        )
    return results


def load_finished_match_results_before_from_db(
    session: Session,
    *,
    cutoff_utc: datetime,
    division_codes: Sequence[str] | None = None,
) -> list[MatchResult]:
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
            Match.kickoff_utc < cutoff_utc,
            Match.status == "finished",
            Match.home_goals.is_not(None),
            Match.away_goals.is_not(None),
        )
        .order_by(Match.kickoff_utc, Match.id, odds_preference, Odd.is_closing.desc(), Odd.id)
    )
    if league_codes:
        statement = statement.where(League.code.in_(league_codes))

    results: list[MatchResult] = []
    seen_match_ids: set[int] = set()
    for row in session.execute(statement):
        match = cast(Match, row[0])
        if match.id in seen_match_ids:
            continue
        seen_match_ids.add(match.id)
        results.append(
            match_result_from_db_row(
                match=match,
                league=cast(League, row[1]),
                season=cast(Season, row[2]),
                home_team_name=cast(str, row[3]),
                away_team_name=cast(str, row[4]),
                odd=cast(Odd | None, row[5]),
            )
        )
    return results


def match_result_from_db_row(
    *,
    match: Match,
    league: League,
    season: Season,
    home_team_name: str,
    away_team_name: str,
    odd: Odd | None,
) -> MatchResult:
    home_goals = _required_score(match.home_goals, "home_goals")
    away_goals = _required_score(match.away_goals, "away_goals")
    home_odds, draw_odds, away_odds, odds_source = _odds_from_db(odd)
    return MatchResult(
        kickoff_utc=match.kickoff_utc,
        season=season_code_from_years(season.year_start, season.year_end),
        division=division_code_for_league(league),
        home_team=home_team_name,
        away_team=away_team_name,
        home_goals=home_goals,
        away_goals=away_goals,
        outcome=result_from_goals(home_goals, away_goals),
        avg_home_odds=home_odds,
        avg_draw_odds=draw_odds,
        avg_away_odds=away_odds,
        odds_source=odds_source,
        match_id=match.id,
    )


def league_codes_from_divisions(division_codes: Sequence[str] | None) -> list[str]:
    if division_codes is None:
        return []
    league_codes: list[str] = []
    for division_code in division_codes:
        normalized = division_code.upper()
        try:
            division = DIVISIONS_BY_CODE[normalized]
        except KeyError as exc:
            supported = ", ".join(sorted(DIVISIONS_BY_CODE))
            msg = f"unsupported division {normalized!r}; supported divisions: {supported}"
            raise ValueError(msg) from exc
        league_codes.append(division.league_code)
    return league_codes


def division_code_for_league(league: League) -> str:
    source_ids = league.source_ids or {}
    source_division = source_ids.get(SOURCE_NAME)
    if isinstance(source_division, str) and source_division:
        return source_division
    return league.code


def season_code_from_years(year_start: int, year_end: int) -> str:
    if year_end != year_start + 1:
        msg = f"season years must be consecutive, got {year_start}-{year_end}"
        raise ValueError(msg)
    return normalize_season_code(f"{year_start % 100:02d}{year_end % 100:02d}")


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


def _required_score(value: int | None, field_name: str) -> int:
    if value is None:
        msg = f"finished match is missing {field_name}"
        raise ValueError(msg)
    return value

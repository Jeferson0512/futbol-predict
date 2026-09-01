"""Ficha de partido: agrega todo lo que mira el modelo para un partido.

Reune datos ya presentes en la base (equipos, cuota de mercado con su
probabilidad implicita, Elo previo, xG rodante desde features, forma reciente y
cara a cara) para la vista de detalle del frontend.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import cast

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session, aliased

from futpredict.data.db_matches import division_code_for_league, season_code_from_years
from futpredict.db.models import EloRating, Feature, League, Match, Odd, Season, Team
from futpredict.features.rolling import FEATURE_SET_VERSION_V2
from futpredict.ingest.normalized import MARKET_1X2


def load_match_detail(session: Session, match_id: int) -> dict[str, object] | None:
    home_team = aliased(Team)
    away_team = aliased(Team)
    row = session.execute(
        select(Match, League, Season, home_team.name, away_team.name)
        .join(League, League.id == Match.league_id)
        .join(Season, Season.id == Match.season_id)
        .join(home_team, home_team.id == Match.home_team_id)
        .join(away_team, away_team.id == Match.away_team_id)
        .where(Match.id == match_id)
    ).first()
    if row is None:
        return None

    match = cast(Match, row[0])
    league = cast(League, row[1])
    season = cast(Season, row[2])
    home_name = cast(str, row[3])
    away_name = cast(str, row[4])

    odds_home, odds_draw, odds_away = _market_odds(session, match_id)
    return {
        "match_id": match.id,
        "kickoff_utc": match.kickoff_utc,
        "league": league.name,
        "division": division_code_for_league(league),
        "season": season_code_from_years(season.year_start, season.year_end),
        "status": match.status,
        "home_team": home_name,
        "away_team": away_name,
        "home_goals": match.home_goals,
        "away_goals": match.away_goals,
        "odds_home": odds_home,
        "odds_draw": odds_draw,
        "odds_away": odds_away,
        "implied": _implied_probabilities(odds_home, odds_draw, odds_away),
        "home_elo_before": _elo_before(session, match_id, match.home_team_id),
        "away_elo_before": _elo_before(session, match_id, match.away_team_id),
        "xg": _xg_features(session, match_id),
        "home_form": _team_form(session, match.home_team_id, match.kickoff_utc),
        "away_form": _team_form(session, match.away_team_id, match.kickoff_utc),
        "head_to_head": _head_to_head(
            session,
            match.home_team_id,
            match.away_team_id,
            match.kickoff_utc,
        ),
    }


def _market_odds(
    session: Session,
    match_id: int,
) -> tuple[float | None, float | None, float | None]:
    odd = session.execute(
        select(Odd)
        .where(Odd.match_id == match_id, Odd.market == MARKET_1X2)
        .order_by((Odd.bookmaker != "market_average"), Odd.id)
    ).scalars().first()
    if odd is None:
        return None, None, None
    return float(odd.odd_home), float(odd.odd_draw), float(odd.odd_away)


def _implied_probabilities(
    odds_home: float | None,
    odds_draw: float | None,
    odds_away: float | None,
) -> list[float] | None:
    if odds_home is None or odds_draw is None or odds_away is None:
        return None
    if odds_home <= 1 or odds_draw <= 1 or odds_away <= 1:
        return None
    raw = [1 / odds_home, 1 / odds_draw, 1 / odds_away]
    total = sum(raw)
    return [value / total for value in raw]


def _elo_before(session: Session, match_id: int, team_id: int) -> float | None:
    rating = session.execute(
        select(EloRating.rating_before).where(
            EloRating.match_id == match_id,
            EloRating.team_id == team_id,
        )
    ).scalar_one_or_none()
    return None if rating is None else float(rating)


def _xg_features(session: Session, match_id: int) -> dict[str, float | None]:
    payload = session.execute(
        select(Feature.payload).where(
            Feature.match_id == match_id,
            Feature.feature_set_version == FEATURE_SET_VERSION_V2,
        )
    ).scalar_one_or_none()
    keys = (
        "home_xg_for_per_match_last_5",
        "home_xg_against_per_match_last_5",
        "away_xg_for_per_match_last_5",
        "away_xg_against_per_match_last_5",
    )
    if payload is None:
        return dict.fromkeys(keys)
    data = cast("dict[str, float | int | None]", payload)
    return {key: _optional_float(data.get(key)) for key in keys}


def _team_form(
    session: Session,
    team_id: int,
    before_kickoff: datetime,
    limit: int = 5,
) -> list[str]:
    rows = session.execute(
        select(Match.home_team_id, Match.home_goals, Match.away_goals)
        .where(
            or_(Match.home_team_id == team_id, Match.away_team_id == team_id),
            Match.kickoff_utc < before_kickoff,
            Match.status == "finished",
            Match.home_goals.is_not(None),
            Match.away_goals.is_not(None),
        )
        .order_by(Match.kickoff_utc.desc())
        .limit(limit)
    ).all()
    form: list[str] = []
    for home_id, home_goals, away_goals in rows:
        is_home = home_id == team_id
        scored = home_goals if is_home else away_goals
        conceded = away_goals if is_home else home_goals
        form.append("W" if scored > conceded else "D" if scored == conceded else "L")
    return form


def _head_to_head(
    session: Session,
    home_team_id: int,
    away_team_id: int,
    before_kickoff: datetime,
    limit: int = 5,
) -> list[dict[str, object]]:
    home_team = aliased(Team)
    away_team = aliased(Team)
    rows = session.execute(
        select(
            Match.kickoff_utc,
            home_team.name,
            away_team.name,
            Match.home_goals,
            Match.away_goals,
        )
        .join(home_team, home_team.id == Match.home_team_id)
        .join(away_team, away_team.id == Match.away_team_id)
        .where(
            or_(
                and_(Match.home_team_id == home_team_id, Match.away_team_id == away_team_id),
                and_(Match.home_team_id == away_team_id, Match.away_team_id == home_team_id),
            ),
            Match.kickoff_utc < before_kickoff,
            Match.status == "finished",
            Match.home_goals.is_not(None),
            Match.away_goals.is_not(None),
        )
        .order_by(Match.kickoff_utc.desc())
        .limit(limit)
    ).all()
    return [
        {
            "kickoff_utc": kickoff,
            "home_team": cast(str, home_name),
            "away_team": cast(str, away_name),
            "home_goals": cast(int, home_goals),
            "away_goals": cast(int, away_goals),
        }
        for kickoff, home_name, away_name, home_goals, away_goals in rows
    ]


def _optional_float(value: object) -> float | None:
    if value is None:
        return None
    if isinstance(value, Decimal | float | int):
        return float(value)
    return float(str(value))

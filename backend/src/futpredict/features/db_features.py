from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import cast

from sqlalchemy import Table, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from futpredict.data.db_matches import league_codes_from_divisions
from futpredict.data.football_data_uk_catalog import season_range, season_years
from futpredict.db.models import Feature, League, Match, Season
from futpredict.features.rolling import FeatureMatch, FeatureSnapshot


@dataclass(frozen=True)
class FeaturePersistenceSummary:
    feature_set_version: str
    features: int


def load_feature_matches_from_db(
    session: Session,
    *,
    start_season: str,
    end_season: str,
    division_codes: Sequence[str] | None = None,
) -> list[FeatureMatch]:
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

    matches: list[FeatureMatch] = []
    for row in session.execute(statement):
        matches.append(
            FeatureMatch(
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


def upsert_feature_snapshots(
    session: Session,
    snapshots: Sequence[FeatureSnapshot],
    *,
    computed_at: datetime | None = None,
    commit: bool = True,
) -> FeaturePersistenceSummary:
    timestamp = computed_at if computed_at is not None else datetime.now(UTC)
    table = cast(Table, Feature.__table__)
    for snapshot in snapshots:
        base = insert(table).values(
            match_id=snapshot.match_id,
            feature_set_version=snapshot.feature_set_version,
            cutoff_utc=snapshot.cutoff_utc,
            payload=snapshot.payload,
            computed_at=timestamp,
        )
        statement = base.on_conflict_do_update(
            index_elements=[table.c.match_id, table.c.feature_set_version],
            set_={
                "cutoff_utc": base.excluded.cutoff_utc,
                "payload": base.excluded.payload,
                "computed_at": base.excluded.computed_at,
            },
        )
        session.execute(statement)

    if commit:
        session.commit()

    version = snapshots[0].feature_set_version if snapshots else ""
    return FeaturePersistenceSummary(feature_set_version=version, features=len(snapshots))


def _required_score(value: int | None, field_name: str) -> int:
    if value is None:
        msg = f"finished match is missing {field_name}"
        raise ValueError(msg)
    return value

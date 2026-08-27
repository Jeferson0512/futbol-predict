from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from futpredict.data.football_data_uk_catalog import (
    DIVISIONS_BY_CODE,
    Division,
    normalize_season_code,
    season_years,
)
from futpredict.domain.fixtures import Fixture
from futpredict.domain.matches import MatchResult

SOURCE_NAME = "football-data.co.uk"
MARKET_1X2 = "1x2"

type LeagueKey = str
type SeasonKey = tuple[str, int, int]
type TeamKey = tuple[str, str]
type MatchKey = tuple[str, str, datetime, str, str]
type OddKey = tuple[MatchKey, str, str]

BOOKMAKER_BY_ODDS_SOURCE: Mapping[str, str] = {
    "avg_closing": "market_average",
    "avg": "market_average",
    "legacy_avg": "market_average",
    "pinnacle_closing": "pinnacle",
    "pinnacle": "pinnacle",
    "bet365_closing": "bet365",
    "bet365": "bet365",
}


@dataclass(frozen=True)
class LeagueRecord:
    key: LeagueKey
    code: str
    name: str
    country: str
    tier: int
    source_ids: Mapping[str, str]


@dataclass(frozen=True)
class SeasonRecord:
    key: SeasonKey
    league_code: str
    year_start: int
    year_end: int
    source_season: str


@dataclass(frozen=True)
class TeamRecord:
    key: TeamKey
    league_code: str
    name: str
    canonical_name: str
    aliases: tuple[str, ...]
    source_ids: Mapping[str, str]


@dataclass(frozen=True)
class MatchRecord:
    key: MatchKey
    league_code: str
    season_code: str
    season_key: SeasonKey
    kickoff_utc: datetime
    status: str
    home_team_key: TeamKey
    away_team_key: TeamKey
    home_goals: int | None
    away_goals: int | None
    outcome: str | None
    source: str
    raw: Mapping[str, object]


@dataclass(frozen=True)
class OddRecord:
    key: OddKey
    match_key: MatchKey
    bookmaker: str
    market: str
    odd_home: Decimal
    odd_draw: Decimal
    odd_away: Decimal
    captured_at: datetime | None
    is_closing: bool
    source: str


@dataclass(frozen=True)
class NormalizedBatch:
    leagues: tuple[LeagueRecord, ...]
    seasons: tuple[SeasonRecord, ...]
    teams: tuple[TeamRecord, ...]
    matches: tuple[MatchRecord, ...]
    odds: tuple[OddRecord, ...]


@dataclass(frozen=True)
class NormalizedBatchValidation:
    duplicate_league_keys: tuple[LeagueKey, ...]
    duplicate_season_keys: tuple[SeasonKey, ...]
    duplicate_team_keys: tuple[TeamKey, ...]
    duplicate_match_keys: tuple[MatchKey, ...]
    duplicate_odd_keys: tuple[OddKey, ...]
    orphan_odd_match_keys: tuple[MatchKey, ...]
    missing_odds_match_keys: tuple[MatchKey, ...]

    @property
    def has_errors(self) -> bool:
        return bool(
            self.duplicate_league_keys
            or self.duplicate_season_keys
            or self.duplicate_team_keys
            or self.duplicate_match_keys
            or self.duplicate_odd_keys
            or self.orphan_odd_match_keys
        )

    @property
    def has_warnings(self) -> bool:
        return bool(self.missing_odds_match_keys)


@dataclass(frozen=True)
class NormalizedBatchSummary:
    leagues: int
    seasons: int
    teams: int
    team_aliases: int
    matches: int
    odds: int
    missing_odds: int
    duplicate_matches: int
    duplicate_odds: int


def build_normalized_batch(matches: Sequence[MatchResult]) -> NormalizedBatch:
    leagues_by_key: dict[LeagueKey, LeagueRecord] = {}
    seasons_by_key: dict[SeasonKey, SeasonRecord] = {}
    team_aliases: dict[TeamKey, list[str]] = {}
    match_records: list[MatchRecord] = []
    odd_records: list[OddRecord] = []

    for match in sorted(matches, key=lambda item: item.kickoff_utc):
        division = _division_for_match(match)
        league = _league_record(division)
        leagues_by_key[league.key] = league

        season_code = normalize_season_code(match.season)
        year_start, year_end = season_years(season_code)
        season_key = (league.key, year_start, year_end)
        seasons_by_key[season_key] = SeasonRecord(
            key=season_key,
            league_code=league.key,
            year_start=year_start,
            year_end=year_end,
            source_season=season_code,
        )

        home_team_key = _record_team(team_aliases, league.key, match.home_team)
        away_team_key = _record_team(team_aliases, league.key, match.away_team)
        match_key = (
            league.key,
            season_code,
            match.kickoff_utc,
            home_team_key[1],
            away_team_key[1],
        )
        match_records.append(
            MatchRecord(
                key=match_key,
                league_code=league.key,
                season_code=season_code,
                season_key=season_key,
                kickoff_utc=match.kickoff_utc,
                status="finished",
                home_team_key=home_team_key,
                away_team_key=away_team_key,
                home_goals=match.home_goals,
                away_goals=match.away_goals,
                outcome=match.outcome,
                source=SOURCE_NAME,
                raw={
                    "division": match.division.upper(),
                    "season": season_code,
                    "odds_source": match.odds_source,
                },
            )
        )

        if _has_complete_odds(match):
            bookmaker = BOOKMAKER_BY_ODDS_SOURCE[str(match.odds_source)]
            odd_records.append(
                OddRecord(
                    key=(match_key, bookmaker, MARKET_1X2),
                    match_key=match_key,
                    bookmaker=bookmaker,
                    market=MARKET_1X2,
                    odd_home=_decimal(match.avg_home_odds),
                    odd_draw=_decimal(match.avg_draw_odds),
                    odd_away=_decimal(match.avg_away_odds),
                    captured_at=None,
                    is_closing=str(match.odds_source).endswith("_closing"),
                    source=f"{SOURCE_NAME}:{match.odds_source}",
                )
            )

    teams = tuple(
        TeamRecord(
            key=key,
            league_code=key[0],
            name=aliases[0],
            canonical_name=key[1],
            aliases=tuple(aliases),
            source_ids={SOURCE_NAME: aliases[0]},
        )
        for key, aliases in sorted(team_aliases.items(), key=lambda item: item[0])
    )

    return NormalizedBatch(
        leagues=tuple(sorted(leagues_by_key.values(), key=lambda item: item.key)),
        seasons=tuple(sorted(seasons_by_key.values(), key=lambda item: item.key)),
        teams=teams,
        matches=tuple(match_records),
        odds=tuple(odd_records),
    )


def build_normalized_fixture_batch(fixtures: Sequence[Fixture]) -> NormalizedBatch:
    leagues_by_key: dict[LeagueKey, LeagueRecord] = {}
    seasons_by_key: dict[SeasonKey, SeasonRecord] = {}
    team_aliases: dict[TeamKey, list[str]] = {}
    match_records: list[MatchRecord] = []
    odd_records: list[OddRecord] = []

    for fixture in sorted(fixtures, key=lambda item: item.kickoff_utc):
        division = _division_for_match(fixture)
        league = _league_record(division)
        leagues_by_key[league.key] = league

        season_code = normalize_season_code(fixture.season)
        year_start, year_end = season_years(season_code)
        season_key = (league.key, year_start, year_end)
        seasons_by_key[season_key] = SeasonRecord(
            key=season_key,
            league_code=league.key,
            year_start=year_start,
            year_end=year_end,
            source_season=season_code,
        )

        home_team_key = _record_team(team_aliases, league.key, fixture.home_team)
        away_team_key = _record_team(team_aliases, league.key, fixture.away_team)
        match_key = (
            league.key,
            season_code,
            fixture.kickoff_utc,
            home_team_key[1],
            away_team_key[1],
        )
        match_records.append(
            MatchRecord(
                key=match_key,
                league_code=league.key,
                season_code=season_code,
                season_key=season_key,
                kickoff_utc=fixture.kickoff_utc,
                status=fixture.status,
                home_team_key=home_team_key,
                away_team_key=away_team_key,
                home_goals=None,
                away_goals=None,
                outcome=None,
                source=SOURCE_NAME,
                raw={
                    "division": fixture.division.upper(),
                    "season": season_code,
                    "odds_source": fixture.odds_source,
                    "status": fixture.status,
                },
            )
        )

        if _has_complete_odds(fixture):
            bookmaker = BOOKMAKER_BY_ODDS_SOURCE[str(fixture.odds_source)]
            odd_records.append(
                OddRecord(
                    key=(match_key, bookmaker, MARKET_1X2),
                    match_key=match_key,
                    bookmaker=bookmaker,
                    market=MARKET_1X2,
                    odd_home=_decimal(fixture.avg_home_odds),
                    odd_draw=_decimal(fixture.avg_draw_odds),
                    odd_away=_decimal(fixture.avg_away_odds),
                    captured_at=None,
                    is_closing=str(fixture.odds_source).endswith("_closing"),
                    source=f"{SOURCE_NAME}:{fixture.odds_source}",
                )
            )

    teams = tuple(
        TeamRecord(
            key=key,
            league_code=key[0],
            name=aliases[0],
            canonical_name=key[1],
            aliases=tuple(aliases),
            source_ids={SOURCE_NAME: aliases[0]},
        )
        for key, aliases in sorted(team_aliases.items(), key=lambda item: item[0])
    )

    return NormalizedBatch(
        leagues=tuple(sorted(leagues_by_key.values(), key=lambda item: item.key)),
        seasons=tuple(sorted(seasons_by_key.values(), key=lambda item: item.key)),
        teams=teams,
        matches=tuple(match_records),
        odds=tuple(odd_records),
    )


def validate_normalized_batch(batch: NormalizedBatch) -> NormalizedBatchValidation:
    match_keys = tuple(match.key for match in batch.matches)
    odd_keys = tuple(odd.key for odd in batch.odds)
    match_key_set = set(match_keys)
    odd_match_keys = tuple(odd.match_key for odd in batch.odds)

    return NormalizedBatchValidation(
        duplicate_league_keys=_duplicates(tuple(league.key for league in batch.leagues)),
        duplicate_season_keys=_duplicates(tuple(season.key for season in batch.seasons)),
        duplicate_team_keys=_duplicates(tuple(team.key for team in batch.teams)),
        duplicate_match_keys=_duplicates(match_keys),
        duplicate_odd_keys=_duplicates(odd_keys),
        orphan_odd_match_keys=tuple(key for key in odd_match_keys if key not in match_key_set),
        missing_odds_match_keys=tuple(key for key in match_keys if key not in set(odd_match_keys)),
    )


def summarize_normalized_batch(
    batch: NormalizedBatch,
    validation: NormalizedBatchValidation | None = None,
) -> NormalizedBatchSummary:
    checked = validation if validation is not None else validate_normalized_batch(batch)
    return NormalizedBatchSummary(
        leagues=len(batch.leagues),
        seasons=len(batch.seasons),
        teams=len(batch.teams),
        team_aliases=sum(len(team.aliases) for team in batch.teams),
        matches=len(batch.matches),
        odds=len(batch.odds),
        missing_odds=len(checked.missing_odds_match_keys),
        duplicate_matches=len(checked.duplicate_match_keys),
        duplicate_odds=len(checked.duplicate_odd_keys),
    )


def canonical_team_name(name: str) -> str:
    return " ".join(name.strip().casefold().split())


def _division_for_match(match: MatchResult | Fixture) -> Division:
    division_code = match.division.upper()
    try:
        return DIVISIONS_BY_CODE[division_code]
    except KeyError as exc:
        supported = ", ".join(sorted(DIVISIONS_BY_CODE))
        msg = f"unsupported division {division_code!r}; supported divisions: {supported}"
        raise ValueError(msg) from exc


def _league_record(division: Division) -> LeagueRecord:
    return LeagueRecord(
        key=division.league_code,
        code=division.league_code,
        name=division.name,
        country=division.country,
        tier=1,
        source_ids={SOURCE_NAME: division.code},
    )


def _record_team(team_aliases: dict[TeamKey, list[str]], league_code: str, name: str) -> TeamKey:
    display_name = " ".join(name.strip().split())
    canonical_name = canonical_team_name(display_name)
    key = (league_code, canonical_name)
    aliases = team_aliases.setdefault(key, [])
    if display_name not in aliases:
        aliases.append(display_name)
    return key


def _has_complete_odds(match: MatchResult | Fixture) -> bool:
    return (
        match.avg_home_odds is not None
        and match.avg_draw_odds is not None
        and match.avg_away_odds is not None
        and match.odds_source is not None
        and match.odds_source in BOOKMAKER_BY_ODDS_SOURCE
    )


def _decimal(value: float | None) -> Decimal:
    if value is None:
        msg = "cannot convert missing odds to Decimal"
        raise ValueError(msg)
    return Decimal(str(value))


def _duplicates[T](values: tuple[T, ...]) -> tuple[T, ...]:
    counts = Counter(values)
    return tuple(value for value, count in counts.items() if count > 1)

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from io import StringIO
from math import isnan
from pathlib import Path
from typing import Any

import httpx
import pandas as pd

from futpredict.data.football_data_uk_catalog import normalize_season_code
from futpredict.domain.fixtures import Fixture
from futpredict.domain.matches import MatchResult, result_from_goals

BASE_URL = "https://www.football-data.co.uk/mmz4281"
FIXTURES_URL = "https://www.football-data.co.uk/fixtures.csv"
DEFAULT_CACHE_DIR = Path("data/raw/football-data-uk")
OddsSelection = tuple[float | None, float | None, float | None, str | None]
FIXTURE_COLUMN_RENAMES = {
    "\ufeffDiv": "division",
    "Div": "division",
    "Date": "match_date",
    "Time": "match_time",
    "HomeTeam": "home_team",
    "AwayTeam": "away_team",
    "FTHG": "home_goals",
    "FTAG": "away_goals",
    "FTR": "full_time_result",
    "HTHG": "home_half_time_goals",
    "HTAG": "away_half_time_goals",
    "HTR": "half_time_result",
    "AvgH": "avg_home_odds",
    "AvgD": "avg_draw_odds",
    "AvgA": "avg_away_odds",
    "AvgCH": "avg_closing_home_odds",
    "AvgCD": "avg_closing_draw_odds",
    "AvgCA": "avg_closing_away_odds",
    "BbAvH": "legacy_avg_home_odds",
    "BbAvD": "legacy_avg_draw_odds",
    "BbAvA": "legacy_avg_away_odds",
    "PSH": "pinnacle_home_odds",
    "PSD": "pinnacle_draw_odds",
    "PSA": "pinnacle_away_odds",
    "PSCH": "pinnacle_closing_home_odds",
    "PSCD": "pinnacle_closing_draw_odds",
    "PSCA": "pinnacle_closing_away_odds",
    "B365H": "bet365_home_odds",
    "B365D": "bet365_draw_odds",
    "B365A": "bet365_away_odds",
    "B365CH": "bet365_closing_home_odds",
    "B365CD": "bet365_closing_draw_odds",
    "B365CA": "bet365_closing_away_odds",
    "MaxH": "max_home_odds",
    "MaxD": "max_draw_odds",
    "MaxA": "max_away_odds",
}
ODDS_PRIORITY = (
    ("avg_closing_home_odds", "avg_closing_draw_odds", "avg_closing_away_odds", "avg_closing"),
    ("avg_home_odds", "avg_draw_odds", "avg_away_odds", "avg"),
    ("legacy_avg_home_odds", "legacy_avg_draw_odds", "legacy_avg_away_odds", "legacy_avg"),
    (
        "pinnacle_closing_home_odds",
        "pinnacle_closing_draw_odds",
        "pinnacle_closing_away_odds",
        "pinnacle_closing",
    ),
    ("pinnacle_home_odds", "pinnacle_draw_odds", "pinnacle_away_odds", "pinnacle"),
    (
        "bet365_closing_home_odds",
        "bet365_closing_draw_odds",
        "bet365_closing_away_odds",
        "bet365_closing",
    ),
    ("bet365_home_odds", "bet365_draw_odds", "bet365_away_odds", "bet365"),
)


@dataclass(frozen=True)
class FootballDataUkFile:
    season: str
    division: str

    @property
    def url(self) -> str:
        return f"{BASE_URL}/{self.season}/{self.division}.csv"


def cache_path(season: str, division: str, cache_dir: Path | str = DEFAULT_CACHE_DIR) -> Path:
    season_code = normalize_season_code(season)
    return Path(cache_dir) / season_code / f"{division.upper()}.csv"


def download_csv_text(season: str, division: str, timeout: float = 30.0) -> str:
    source = FootballDataUkFile(season=normalize_season_code(season), division=division.upper())
    response = httpx.get(source.url, timeout=timeout)
    response.raise_for_status()
    return response.text


def download_csv(
    season: str,
    division: str,
    cache_dir: Path | str = DEFAULT_CACHE_DIR,
    force: bool = False,
    timeout: float = 30.0,
) -> Path:
    path = cache_path(season, division, cache_dir)
    if path.exists() and not force:
        return path

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(download_csv_text(season, division, timeout=timeout), encoding="utf-8")
    return path


def download_many(
    seasons: list[str],
    divisions: list[str],
    cache_dir: Path | str = DEFAULT_CACHE_DIR,
    force: bool = False,
    timeout: float = 30.0,
) -> list[Path]:
    paths: list[Path] = []
    for season in seasons:
        for division in divisions:
            paths.append(
                download_csv(
                    season=season,
                    division=division,
                    cache_dir=cache_dir,
                    force=force,
                    timeout=timeout,
                )
            )
    return paths


def download_fixtures_csv_text(timeout: float = 30.0) -> str:
    response = httpx.get(FIXTURES_URL, timeout=timeout)
    response.raise_for_status()
    return response.text


def download_fixtures_csv(
    cache_dir: Path | str = DEFAULT_CACHE_DIR,
    force: bool = False,
    timeout: float = 30.0,
) -> Path:
    path = Path(cache_dir) / "fixtures.csv"
    if path.exists() and not force:
        return path

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(download_fixtures_csv_text(timeout=timeout), encoding="utf-8")
    return path


def read_csv_file(
    path: Path | str,
    season: str | None = None,
    division: str | None = None,
) -> pd.DataFrame:
    frame = pd.read_csv(Path(path))
    normalized = normalize_columns(frame).copy()
    if season is not None:
        normalized = normalized.assign(season=normalize_season_code(season))
    if division is not None:
        normalized = normalized.assign(division=division.upper())
    return normalized


def read_fixture_csv_file(path: Path | str) -> pd.DataFrame:
    frame = pd.read_csv(Path(path))
    return normalize_fixture_columns(frame)


def read_csv_from_text(text: str) -> pd.DataFrame:
    frame = pd.read_csv(StringIO(text))
    return normalize_columns(frame)


def read_fixture_csv_from_text(text: str) -> pd.DataFrame:
    frame = pd.read_csv(StringIO(text))
    return normalize_fixture_columns(frame)


def fetch_csv(season: str, division: str, timeout: float = 30.0) -> pd.DataFrame:
    frame = read_csv_from_text(download_csv_text(season, division, timeout=timeout)).copy()
    return frame.assign(season=normalize_season_code(season), division=division.upper())


def fetch_fixtures_csv(timeout: float = 30.0) -> pd.DataFrame:
    return read_fixture_csv_from_text(download_fixtures_csv_text(timeout=timeout))


def normalize_columns(frame: pd.DataFrame) -> pd.DataFrame:
    normalized = normalize_fixture_columns(frame)
    required = {
        "match_date",
        "home_team",
        "away_team",
        "home_goals",
        "away_goals",
        "full_time_result",
    }
    missing = required.difference(normalized.columns)
    if missing:
        msg = f"football-data.co.uk CSV missing required columns: {sorted(missing)}"
        raise ValueError(msg)
    return normalized.dropna(subset=["home_team", "away_team", "home_goals", "away_goals"])


def normalize_fixture_columns(frame: pd.DataFrame) -> pd.DataFrame:
    normalized = frame.rename(columns=FIXTURE_COLUMN_RENAMES)
    required = {"match_date", "home_team", "away_team"}
    missing = required.difference(normalized.columns)
    if missing:
        msg = f"football-data.co.uk fixtures CSV missing required columns: {sorted(missing)}"
        raise ValueError(msg)
    return normalized.dropna(subset=["match_date", "home_team", "away_team"])


def parse_matches(frame: pd.DataFrame, season: str, division: str) -> list[MatchResult]:
    rows: list[MatchResult] = []
    normalized = normalize_columns(frame)
    for raw_record in normalized.to_dict(orient="records"):
        record = {str(key): value for key, value in raw_record.items()}
        home_goals = int(record["home_goals"])
        away_goals = int(record["away_goals"])
        kickoff = parse_kickoff(record.get("match_date"), record.get("match_time"))
        home_odds, draw_odds, away_odds, odds_source = _select_market_odds(record)
        rows.append(
            MatchResult(
                kickoff_utc=kickoff,
                season=normalize_season_code(season),
                division=division.upper(),
                home_team=str(record["home_team"]),
                away_team=str(record["away_team"]),
                home_goals=home_goals,
                away_goals=away_goals,
                outcome=str(
                    record.get("full_time_result") or result_from_goals(home_goals, away_goals)
                ),
                avg_home_odds=home_odds,
                avg_draw_odds=draw_odds,
                avg_away_odds=away_odds,
                odds_source=odds_source,
            )
        )
    return sorted(rows, key=lambda match: match.kickoff_utc)


def parse_fixtures(
    frame: pd.DataFrame,
    season: str,
    division: str | None = None,
) -> list[Fixture]:
    rows: list[Fixture] = []
    season_code = normalize_season_code(season)
    normalized = normalize_fixture_columns(frame)
    for raw_record in normalized.to_dict(orient="records"):
        record = {str(key): value for key, value in raw_record.items()}
        division_code = _fixture_division(record, division)
        if division_code is None:
            continue
        if _has_result(record):
            continue

        kickoff = parse_kickoff(record.get("match_date"), record.get("match_time"))
        home_odds, draw_odds, away_odds, odds_source = _select_market_odds(record)
        rows.append(
            Fixture(
                kickoff_utc=kickoff,
                season=season_code,
                division=division_code,
                home_team=str(record["home_team"]),
                away_team=str(record["away_team"]),
                avg_home_odds=home_odds,
                avg_draw_odds=draw_odds,
                avg_away_odds=away_odds,
                odds_source=odds_source,
            )
        )
    return sorted(rows, key=lambda fixture: fixture.kickoff_utc)


def load_matches(
    seasons: list[str],
    divisions: list[str],
    cache_dir: Path | str = DEFAULT_CACHE_DIR,
    force: bool = False,
) -> list[MatchResult]:
    matches: list[MatchResult] = []
    for season in seasons:
        for division in divisions:
            csv_path = download_csv(
                season=season,
                division=division,
                cache_dir=cache_dir,
                force=force,
            )
            frame = read_csv_file(csv_path, season=season, division=division)
            matches.extend(parse_matches(frame, season=season, division=division))
    return sorted(matches, key=lambda match: match.kickoff_utc)


def load_weekly_fixtures(
    season: str,
    divisions: list[str],
    cache_dir: Path | str = DEFAULT_CACHE_DIR,
    force: bool = False,
) -> list[Fixture]:
    csv_path = download_fixtures_csv(cache_dir=cache_dir, force=force)
    frame = read_fixture_csv_file(csv_path)
    allowed_divisions = {division.upper() for division in divisions}
    fixtures = parse_fixtures(frame, season=season)
    return [
        fixture
        for fixture in fixtures
        if fixture.division.upper() in allowed_divisions
    ]


def parse_kickoff(match_date: object, match_time: object | None = None) -> datetime:
    date_text = str(match_date)
    time_text = "" if _is_missing_scalar(match_time) else str(match_time)
    raw_value = f"{date_text} {time_text}".strip()
    parsed = pd.to_datetime(raw_value, dayfirst=True, errors="raise")
    if isinstance(parsed, pd.Timestamp):
        if parsed.tzinfo is None:
            return parsed.tz_localize(UTC).to_pydatetime()
        return parsed.tz_convert(UTC).to_pydatetime()
    msg = f"could not parse kickoff from {raw_value!r}"
    raise ValueError(msg)


def _optional_float(value: object) -> float | None:
    if _is_missing_scalar(value):
        return None
    if isinstance(value, int | float | str):
        return float(value)
    msg = f"expected numeric scalar, got {type(value).__name__}"
    raise TypeError(msg)


def _select_market_odds(record: Mapping[str, Any]) -> OddsSelection:
    for home_key, draw_key, away_key, source in ODDS_PRIORITY:
        home = _optional_float(record.get(home_key))
        draw = _optional_float(record.get(draw_key))
        away = _optional_float(record.get(away_key))
        if home is not None and draw is not None and away is not None:
            return home, draw, away, source
    return None, None, None, None


def _fixture_division(record: Mapping[str, Any], fallback: str | None) -> str | None:
    value = fallback if fallback is not None else record.get("division")
    if _is_missing_scalar(value):
        return None
    return str(value).upper()


def _has_result(record: Mapping[str, Any]) -> bool:
    return (
        not _is_missing_scalar(record.get("home_goals"))
        and not _is_missing_scalar(record.get("away_goals"))
    )


def _is_missing_scalar(value: object | None) -> bool:
    if value is None:
        return True
    if isinstance(value, float):
        return isnan(value)
    if isinstance(value, str):
        return not value.strip()
    return False

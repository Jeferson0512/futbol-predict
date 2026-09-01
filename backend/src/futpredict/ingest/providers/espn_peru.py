"""Adaptador de la Liga 1 de Peru desde el API publico de ESPN.

ESPN (`site.api.espn.com`, liga `per.1`) publica resultados y fixtures de la
Liga 1 peruana sin API key, con historial de varias temporadas. La temporada es
por ano calendario (ene-nov, con Apertura/Clausura); aqui cada ano se trata como
una temporada. Solo trae resultados y programacion (sin cuotas ni xG).
"""

from __future__ import annotations

import calendar
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import httpx

PERU_LEAGUE_CODE = "liga1-peru"
PERU_LEAGUE_NAME = "Liga 1 Peru"
PERU_DIVISION = "PER1"
ESPN_PERU_SLUG = "per.1"
_ESPN_SCOREBOARD = "https://site.api.espn.com/apis/site/v2/sports/soccer/{slug}/scoreboard"
# ESPN responde 403 a User-Agents desconocidos; usar uno de navegador.
_ESPN_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"


@dataclass(frozen=True)
class EspnPeruMatch:
    espn_id: str
    kickoff_utc: datetime
    season: str
    home_team: str
    away_team: str
    home_goals: int | None
    away_goals: int | None
    completed: bool

    @property
    def outcome(self) -> str | None:
        if not self.completed or self.home_goals is None or self.away_goals is None:
            return None
        if self.home_goals > self.away_goals:
            return "H"
        if self.home_goals == self.away_goals:
            return "D"
        return "A"


def fetch_espn_peru_season(
    year: int,
    *,
    timeout: float = 30.0,
    client: httpx.Client | None = None,
) -> list[EspnPeruMatch]:
    owned = client is None
    http = client or httpx.Client(timeout=timeout, headers={"User-Agent": _ESPN_USER_AGENT})
    try:
        events: list[dict[str, Any]] = []
        for month in range(1, 13):
            last_day = calendar.monthrange(year, month)[1]
            start = f"{year}{month:02d}01"
            end = f"{year}{month:02d}{last_day:02d}"
            url = _ESPN_SCOREBOARD.format(slug=ESPN_PERU_SLUG)
            response = http.get(url, params={"dates": f"{start}-{end}"})
            response.raise_for_status()
            events.extend(response.json().get("events", []))
    finally:
        if owned:
            http.close()

    return parse_espn_events(events, season=str(year))


def parse_espn_events(
    events: Iterable[dict[str, Any]],
    *,
    season: str,
) -> list[EspnPeruMatch]:
    matches: dict[str, EspnPeruMatch] = {}
    for event in events:
        parsed = _parse_event(event, season=season)
        if parsed is not None:
            matches[parsed.espn_id] = parsed
    return sorted(matches.values(), key=lambda match: match.kickoff_utc)


def _parse_event(event: dict[str, Any], *, season: str) -> EspnPeruMatch | None:
    competitions = event.get("competitions") or []
    if not competitions:
        return None
    competition = competitions[0]
    competitors = competition.get("competitors") or []
    if len(competitors) != 2:
        return None

    home = next((c for c in competitors if c.get("homeAway") == "home"), None)
    away = next((c for c in competitors if c.get("homeAway") == "away"), None)
    if home is None or away is None:
        return None

    status = competition.get("status", {}).get("type", {})
    completed = bool(status.get("completed"))
    kickoff = _parse_datetime(event.get("date"))
    if kickoff is None:
        return None

    return EspnPeruMatch(
        espn_id=str(event.get("id")),
        kickoff_utc=kickoff,
        season=season,
        home_team=_team_name(home),
        away_team=_team_name(away),
        home_goals=_score(home) if completed else None,
        away_goals=_score(away) if completed else None,
        completed=completed,
    )


def _team_name(competitor: dict[str, Any]) -> str:
    team = competitor.get("team", {})
    return str(team.get("displayName") or team.get("name") or team.get("abbreviation") or "?")


def _score(competitor: dict[str, Any]) -> int | None:
    raw = competitor.get("score")
    if raw is None or raw == "":
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def _parse_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed

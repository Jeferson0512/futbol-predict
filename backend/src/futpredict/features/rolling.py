from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from statistics import fmean

from futpredict.features.guards import FeatureInput, assert_no_leakage

FEATURE_SET_VERSION = "rolling_v1"
RECENT_MATCH_LIMIT = 5

type FeatureValue = float | int | None
type FeaturePayload = dict[str, FeatureValue]


@dataclass(frozen=True)
class FeatureMatch:
    match_id: int
    league_code: str
    kickoff_utc: datetime
    home_team_id: int
    away_team_id: int
    home_goals: int
    away_goals: int


@dataclass(frozen=True)
class TeamMatchHistory:
    kickoff_utc: datetime
    goals_for: int
    goals_against: int
    points: int


@dataclass
class LeagueAggregate:
    home_wins: int = 0
    draws: int = 0
    away_wins: int = 0

    @property
    def total_matches(self) -> int:
        return self.home_wins + self.draws + self.away_wins


@dataclass(frozen=True)
class FeatureSnapshot:
    match_id: int
    feature_set_version: str
    cutoff_utc: datetime
    payload: FeaturePayload


def build_rolling_feature_snapshots(
    matches: Sequence[FeatureMatch],
    *,
    feature_set_version: str = FEATURE_SET_VERSION,
    recent_match_limit: int = RECENT_MATCH_LIMIT,
) -> list[FeatureSnapshot]:
    if recent_match_limit <= 0:
        msg = "recent_match_limit must be positive"
        raise ValueError(msg)

    ordered = sorted(matches, key=lambda match: (match.kickoff_utc, match.match_id))
    team_histories: dict[int, list[TeamMatchHistory]] = {}
    league_aggregates: dict[str, LeagueAggregate] = {}
    league_last_kickoff: dict[str, datetime] = {}
    snapshots: list[FeatureSnapshot] = []
    index = 0

    while index < len(ordered):
        kickoff = ordered[index].kickoff_utc
        same_cutoff_matches: list[FeatureMatch] = []
        while index < len(ordered) and ordered[index].kickoff_utc == kickoff:
            same_cutoff_matches.append(ordered[index])
            index += 1

        for match in same_cutoff_matches:
            home_history = team_histories.get(match.home_team_id, [])
            away_history = team_histories.get(match.away_team_id, [])
            league_aggregate = league_aggregates.get(match.league_code, LeagueAggregate())
            _assert_histories_before_cutoff(
                match,
                home_history,
                away_history,
                league_last_kickoff.get(match.league_code),
            )

            snapshots.append(
                FeatureSnapshot(
                    match_id=match.match_id,
                    feature_set_version=feature_set_version,
                    cutoff_utc=match.kickoff_utc,
                    payload={
                        "home_team_matches_before": len(home_history),
                        "away_team_matches_before": len(away_history),
                        "home_points_per_match_last_5": _avg_points(
                            home_history,
                            recent_match_limit,
                        ),
                        "away_points_per_match_last_5": _avg_points(
                            away_history,
                            recent_match_limit,
                        ),
                        "home_goals_for_per_match_last_5": _avg_goals_for(
                            home_history,
                            recent_match_limit,
                        ),
                        "away_goals_for_per_match_last_5": _avg_goals_for(
                            away_history,
                            recent_match_limit,
                        ),
                        "home_goals_against_per_match_last_5": _avg_goals_against(
                            home_history,
                            recent_match_limit,
                        ),
                        "away_goals_against_per_match_last_5": _avg_goals_against(
                            away_history,
                            recent_match_limit,
                        ),
                        "home_days_since_last_match": _days_since_last_match(
                            home_history,
                            match.kickoff_utc,
                        ),
                        "away_days_since_last_match": _days_since_last_match(
                            away_history,
                            match.kickoff_utc,
                        ),
                        "league_home_win_rate_before": _rate(
                            league_aggregate.home_wins,
                            league_aggregate.total_matches,
                        ),
                        "league_draw_rate_before": _rate(
                            league_aggregate.draws,
                            league_aggregate.total_matches,
                        ),
                        "league_away_win_rate_before": _rate(
                            league_aggregate.away_wins,
                            league_aggregate.total_matches,
                        ),
                    },
                )
            )

        for match in same_cutoff_matches:
            _append_finished_match(team_histories, league_aggregates, league_last_kickoff, match)

    return snapshots


def _append_finished_match(
    team_histories: dict[int, list[TeamMatchHistory]],
    league_aggregates: dict[str, LeagueAggregate],
    league_last_kickoff: dict[str, datetime],
    match: FeatureMatch,
) -> None:
    home_points, away_points = _points(match.home_goals, match.away_goals)
    team_histories.setdefault(match.home_team_id, []).append(
        TeamMatchHistory(
            kickoff_utc=match.kickoff_utc,
            goals_for=match.home_goals,
            goals_against=match.away_goals,
            points=home_points,
        )
    )
    team_histories.setdefault(match.away_team_id, []).append(
        TeamMatchHistory(
            kickoff_utc=match.kickoff_utc,
            goals_for=match.away_goals,
            goals_against=match.home_goals,
            points=away_points,
        )
    )
    aggregate = league_aggregates.setdefault(match.league_code, LeagueAggregate())
    if match.home_goals > match.away_goals:
        aggregate.home_wins += 1
    elif match.home_goals == match.away_goals:
        aggregate.draws += 1
    else:
        aggregate.away_wins += 1
    league_last_kickoff[match.league_code] = match.kickoff_utc


def _assert_histories_before_cutoff(
    match: FeatureMatch,
    home_history: list[TeamMatchHistory],
    away_history: list[TeamMatchHistory],
    league_last_kickoff: datetime | None,
) -> None:
    inputs = [
        *([FeatureInput(name="home_latest_match", observed_at=home_history[-1].kickoff_utc)]
          if home_history
          else []),
        *([FeatureInput(name="away_latest_match", observed_at=away_history[-1].kickoff_utc)]
          if away_history
          else []),
        *([FeatureInput(name="league_latest_match", observed_at=league_last_kickoff)]
          if league_last_kickoff is not None
          else []),
    ]
    assert_no_leakage(inputs, match.kickoff_utc)


def _avg_points(history: list[TeamMatchHistory], limit: int) -> float | None:
    recent = _recent_team_history(history, limit)
    return None if not recent else fmean(item.points for item in recent)


def _avg_goals_for(history: list[TeamMatchHistory], limit: int) -> float | None:
    recent = _recent_team_history(history, limit)
    return None if not recent else fmean(item.goals_for for item in recent)


def _avg_goals_against(history: list[TeamMatchHistory], limit: int) -> float | None:
    recent = _recent_team_history(history, limit)
    return None if not recent else fmean(item.goals_against for item in recent)


def _days_since_last_match(history: list[TeamMatchHistory], cutoff_utc: datetime) -> float | None:
    if not history:
        return None
    last_match = history[-1]
    return (cutoff_utc - last_match.kickoff_utc).total_seconds() / 86_400


def _rate(numerator: int, denominator: int) -> float | None:
    return None if denominator == 0 else numerator / denominator


def _recent_team_history(
    history: list[TeamMatchHistory],
    limit: int,
) -> list[TeamMatchHistory]:
    return history[-limit:]


def _points(home_goals: int, away_goals: int) -> tuple[int, int]:
    if home_goals > away_goals:
        return 3, 0
    if home_goals == away_goals:
        return 1, 1
    return 0, 3

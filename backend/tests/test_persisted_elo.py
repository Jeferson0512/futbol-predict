from __future__ import annotations

from datetime import UTC, datetime
from typing import cast

from sqlalchemy.orm import Session

from futpredict.models.elo import EloConfig
from futpredict.models.persisted_elo import (
    ELO_RATING_SYSTEM,
    EloMatch,
    build_elo_rating_snapshots,
    upsert_elo_rating_snapshots,
)


class RecordingSession:
    def __init__(self) -> None:
        self.executions = 0
        self.committed = False

    def execute(self, _statement: object) -> None:
        self.executions += 1

    def commit(self) -> None:
        self.committed = True


def test_build_elo_rating_snapshots_creates_home_and_away_rows() -> None:
    snapshots = build_elo_rating_snapshots(
        [
            EloMatch(
                match_id=1,
                league_code="premier-league",
                kickoff_utc=datetime(2026, 1, 1, tzinfo=UTC),
                home_team_id=10,
                away_team_id=20,
                home_goals=2,
                away_goals=1,
            )
        ],
        config=EloConfig(k=20.0, home_advantage=0.0, goal_difference_factor=False),
    )

    assert len(snapshots) == 2
    assert snapshots[0].team_id == 10
    assert snapshots[0].rating_before == 1500
    assert snapshots[0].rating_after == 1510
    assert snapshots[1].team_id == 20
    assert snapshots[1].rating_before == 1500
    assert snapshots[1].rating_after == 1490


def test_build_elo_rating_snapshots_isolates_leagues() -> None:
    snapshots = build_elo_rating_snapshots(
        [
            EloMatch(
                match_id=1,
                league_code="premier-league",
                kickoff_utc=datetime(2026, 1, 1, tzinfo=UTC),
                home_team_id=10,
                away_team_id=20,
                home_goals=2,
                away_goals=1,
            ),
            EloMatch(
                match_id=2,
                league_code="laliga",
                kickoff_utc=datetime(2026, 1, 2, tzinfo=UTC),
                home_team_id=10,
                away_team_id=30,
                home_goals=0,
                away_goals=0,
            ),
        ],
        config=EloConfig(k=20.0, home_advantage=0.0, goal_difference_factor=False),
    )

    second_match_home = snapshots[2]

    assert second_match_home.match_id == 2
    assert second_match_home.team_id == 10
    assert second_match_home.rating_before == 1500


def test_upsert_elo_rating_snapshots_is_idempotent_by_team_and_match() -> None:
    snapshots = build_elo_rating_snapshots(
        [
            EloMatch(
                match_id=1,
                league_code="premier-league",
                kickoff_utc=datetime(2026, 1, 1, tzinfo=UTC),
                home_team_id=10,
                away_team_id=20,
                home_goals=2,
                away_goals=1,
            )
        ],
        config=EloConfig(k=20.0, home_advantage=0.0, goal_difference_factor=False),
    )
    session = RecordingSession()

    summary = upsert_elo_rating_snapshots(cast(Session, session), snapshots)

    assert session.executions == 2
    assert session.committed is True
    assert summary.rating_system == ELO_RATING_SYSTEM
    assert summary.matches == 1
    assert summary.ratings == 2

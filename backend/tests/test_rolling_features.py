from __future__ import annotations

from datetime import UTC, datetime

import pytest

from futpredict.features.rolling import (
    FEATURE_SET_VERSION,
    FeatureMatch,
    build_rolling_feature_snapshots,
)


def test_rolling_features_use_only_matches_before_cutoff() -> None:
    first_kickoff = datetime(2026, 1, 1, 15, 0, tzinfo=UTC)
    later_kickoff = datetime(2026, 1, 8, 15, 0, tzinfo=UTC)
    snapshots = build_rolling_feature_snapshots(
        [
            FeatureMatch(
                match_id=1,
                league_code="premier-league",
                kickoff_utc=first_kickoff,
                home_team_id=10,
                away_team_id=20,
                home_goals=2,
                away_goals=1,
            ),
            FeatureMatch(
                match_id=2,
                league_code="premier-league",
                kickoff_utc=first_kickoff,
                home_team_id=30,
                away_team_id=40,
                home_goals=0,
                away_goals=1,
            ),
            FeatureMatch(
                match_id=3,
                league_code="premier-league",
                kickoff_utc=later_kickoff,
                home_team_id=10,
                away_team_id=30,
                home_goals=1,
                away_goals=1,
            ),
        ]
    )

    simultaneous_match = snapshots[1].payload
    later_match = snapshots[2].payload

    assert snapshots[0].feature_set_version == FEATURE_SET_VERSION
    assert simultaneous_match["league_home_win_rate_before"] is None
    assert simultaneous_match["home_team_matches_before"] == 0
    assert later_match["home_team_matches_before"] == 1
    assert later_match["away_team_matches_before"] == 1
    assert later_match["home_points_per_match_last_5"] == 3.0
    assert later_match["away_points_per_match_last_5"] == 0.0
    assert later_match["home_days_since_last_match"] == 7.0
    assert later_match["league_home_win_rate_before"] == 0.5
    assert later_match["league_away_win_rate_before"] == 0.5


def test_rolling_features_reject_non_positive_recent_limit() -> None:
    with pytest.raises(ValueError, match="recent_match_limit"):
        build_rolling_feature_snapshots([], recent_match_limit=0)

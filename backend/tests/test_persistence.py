from __future__ import annotations

from datetime import UTC, datetime
from typing import cast

import pytest
from sqlalchemy.orm import Session

from futpredict.domain.matches import MatchResult
from futpredict.ingest.normalized import build_normalized_batch
from futpredict.ingest.persistence import NormalizedBatchIntegrityError, load_normalized_batch


class RecordingSession:
    executed = False
    committed = False

    def execute(self, _statement: object) -> None:
        self.executed = True

    def commit(self) -> None:
        self.committed = True


def test_load_normalized_batch_rejects_invalid_batch_before_db_calls() -> None:
    match = MatchResult(
        kickoff_utc=datetime(2025, 8, 15, 20, 0, tzinfo=UTC),
        season="2526",
        division="E0",
        home_team="Liverpool",
        away_team="Bournemouth",
        home_goals=4,
        away_goals=2,
        outcome="H",
        avg_home_odds=1.3,
        avg_draw_odds=5.4,
        avg_away_odds=9.0,
        odds_source="avg_closing",
    )
    batch = build_normalized_batch([match, match])
    session = RecordingSession()

    with pytest.raises(NormalizedBatchIntegrityError, match="duplicate matches=1"):
        load_normalized_batch(cast(Session, session), batch)

    assert session.executed is False
    assert session.committed is False

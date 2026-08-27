from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

import httpx
import pytest

from futpredict.domain.matches import MatchResult
from futpredict.ingest.providers import clubelo
from futpredict.ingest.providers.clubelo import (
    api_name_candidates,
    load_team_history,
    parse_team_history_csv,
)
from futpredict.models.club_elo import ClubEloPredictor


def test_api_name_candidates_include_overrides_before_sanitized_name() -> None:
    man_city_candidates = api_name_candidates("Man City")
    assert man_city_candidates[0] == "ManCity"
    assert man_city_candidates.count("ManCity") == 1
    assert api_name_candidates("Nott'm Forest")[0] == "Forest"
    assert api_name_candidates("Ath Bilbao")[0] == "Bilbao"
    assert api_name_candidates("Nurnberg")[0] == "Nuernberg"


def test_load_team_history_continues_after_candidate_timeout(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    calls: list[str] = []

    def fake_download(api_name: str, *, timeout: float) -> str:
        calls.append(api_name)
        if api_name == "SlowName":
            raise httpx.TimeoutException("timed out")
        return "\n".join(
            [
                "Rank,Club,Country,Level,Elo,From,To",
                "1,Fast FC,ENG,1,1700.5,2026-01-01,2026-12-31",
            ]
        )

    monkeypatch.setattr(clubelo, "download_team_history_text", fake_download)

    history = load_team_history(
        "Example",
        cache_dir=tmp_path,
        api_name_overrides={"Example": ("SlowName", "FastName")},
    )

    assert history is not None
    assert history.api_name == "FastName"
    assert calls == ["SlowName", "FastName"]


def test_club_elo_history_finds_rating_inside_date_period() -> None:
    history = parse_team_history_csv(
        "\n".join(
            [
                "Rank,Club,Country,Level,Elo,From,To",
                "1,Example FC,ENG,1,1700.5,2026-01-01,2026-01-09",
                "1,Example FC,ENG,1,1710.5,2026-01-10,2026-12-31",
            ]
        ),
        source_team_name="Example",
        api_name="Example",
    )

    assert history.display_name == "Example FC"
    assert history.rating_on(date(2025, 12, 31)) is None
    assert history.rating_on(date(2026, 1, 5)) == 1700.5
    assert history.rating_on(date(2026, 1, 10)) == 1710.5


def test_club_elo_predictor_uses_previous_day_rating() -> None:
    home = parse_team_history_csv(
        "\n".join(
            [
                "Rank,Club,Country,Level,Elo,From,To",
                "1,Home FC,ENG,1,1600.0,2026-01-01,2026-01-09",
                "1,Home FC,ENG,1,1900.0,2026-01-10,2026-12-31",
            ]
        ),
        source_team_name="Home",
        api_name="Home",
    )
    away = parse_team_history_csv(
        "\n".join(
            [
                "Rank,Club,Country,Level,Elo,From,To",
                "1,Away FC,ENG,1,1600.0,2026-01-01,2026-12-31",
            ]
        ),
        source_team_name="Away",
        api_name="Away",
    )
    predictor = ClubEloPredictor({"Home": home, "Away": away})
    match = MatchResult(
        kickoff_utc=datetime(2026, 1, 10, tzinfo=UTC),
        season="2526",
        division="E0",
        home_team="Home",
        away_team="Away",
        home_goals=2,
        away_goals=1,
        outcome="H",
    )

    prediction = predictor(match)

    assert prediction is not None
    assert prediction.model == "club_elo"
    assert prediction.probabilities[0] < 0.5

from __future__ import annotations

from datetime import UTC, datetime

from futpredict.domain.matches import MatchResult
from futpredict.evaluation.ml_walk_forward import run_ml_walk_forward
from futpredict.models.logistic import FEATURE_KEYS, LOGISTIC_MODEL_NAME


def _match(match_id: int, season: str, month: int, home_goals: int, away_goals: int) -> MatchResult:
    outcome = "H" if home_goals > away_goals else "D" if home_goals == away_goals else "A"
    return MatchResult(
        kickoff_utc=datetime(2000 + int(season[:2]), month, 1, tzinfo=UTC),
        season=season,
        division="E0",
        home_team=f"Home {match_id}",
        away_team=f"Away {match_id}",
        home_goals=home_goals,
        away_goals=away_goals,
        outcome=outcome,
        match_id=match_id,
    )


def _payload(home_points: float, away_points: float) -> dict[str, float | int | None]:
    values: dict[str, float | int | None] = dict.fromkeys(FEATURE_KEYS, 0.0)
    values["home_points_per_match_last_5"] = home_points
    values["away_points_per_match_last_5"] = away_points
    return values


def _season_matches(season: str, start_id: int) -> list[MatchResult]:
    matches: list[MatchResult] = []
    for offset in range(6):
        month = 1 + offset
        if offset % 2 == 0:
            matches.append(_match(start_id + offset, season, month, 2, 0))  # H
        else:
            matches.append(_match(start_id + offset, season, month, 0, 2))  # A
    return matches


def test_ml_walk_forward_evaluates_only_future_seasons() -> None:
    matches = [
        *_season_matches("2021", 100),
        *_season_matches("2122", 200),
        *_season_matches("2223", 300),
    ]
    payloads: dict[int, dict[str, float | int | None]] = {}
    for match in matches:
        assert match.match_id is not None
        if match.outcome == "H":
            payloads[match.match_id] = _payload(3.0, 0.5)
        else:
            payloads[match.match_id] = _payload(0.5, 3.0)

    metrics = run_ml_walk_forward(
        matches,
        payloads,
        start_season="2021",
        end_season="2223",
        initial_train_seasons=2,
        min_train_samples=4,
    )

    assert metrics, "expected at least one logistic walk-forward window"
    assert {metric.summary.model for metric in metrics} == {LOGISTIC_MODEL_NAME}
    assert {metric.evaluation_season for metric in metrics} == {"2223"}
    assert metrics[0].summary.n_matches == 6


def test_ml_walk_forward_skips_windows_without_enough_features() -> None:
    matches = [
        *_season_matches("2021", 100),
        *_season_matches("2122", 200),
        *_season_matches("2223", 300),
    ]
    # Sin payloads no hay muestras de entrenamiento: no debe producir metricas.
    metrics = run_ml_walk_forward(
        matches,
        {},
        start_season="2021",
        end_season="2223",
        initial_train_seasons=2,
        min_train_samples=4,
    )
    assert metrics == []

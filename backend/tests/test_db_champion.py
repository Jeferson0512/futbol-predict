from __future__ import annotations

from typing import Any

from futpredict.evaluation import db_champion


class _FakeScalars:
    def __init__(self, values: list[int]) -> None:
        self._values = values

    def all(self) -> list[int]:
        return self._values


class _FakeResult:
    def __init__(self, rowcount: int = 0, scalars: list[int] | None = None) -> None:
        self.rowcount = rowcount
        self._scalars = scalars or []

    def scalars(self) -> _FakeScalars:
        return _FakeScalars(self._scalars)


class _FakeSession:
    def __init__(self, results: list[_FakeResult]) -> None:
        self._results = list(results)
        self.committed = False
        self.calls = 0

    def execute(self, _statement: Any) -> _FakeResult:
        self.calls += 1
        return self._results.pop(0)

    def commit(self) -> None:
        self.committed = True


def test_promote_champion_marks_one_version_per_league(monkeypatch: Any) -> None:
    monkeypatch.setattr(
        db_champion,
        "champion_model_row",
        lambda _session, min_matches=100: {
            "model": "market_avg_odds",
            "algorithm": "market_odds",
            "feature_set_version": "baseline_walk_forward_v1",
            "weighted_rps": 0.1956,
            "matches": 12459,
            "windows": 35,
        },
    )
    session = _FakeSession(
        [
            _FakeResult(rowcount=3),  # clear champions vigentes
            _FakeResult(scalars=[10, 20, 30, 40, 50]),  # una version por liga
            _FakeResult(rowcount=5),  # promover
        ]
    )

    summary = db_champion.promote_champion_by_rps(session, min_matches=100)  # type: ignore[arg-type]

    assert summary.champion_model == "market_avg_odds"
    assert summary.demoted_versions == 3
    assert summary.promoted_versions == 5
    assert summary.champion_versions == 5
    assert summary.weighted_rps == 0.1956
    assert session.committed is True


def test_promote_champion_without_ranked_models_demotes_all(monkeypatch: Any) -> None:
    monkeypatch.setattr(
        db_champion,
        "champion_model_row",
        lambda _session, min_matches=100: None,
    )
    session = _FakeSession([_FakeResult(rowcount=7)])  # solo el clear

    summary = db_champion.promote_champion_by_rps(session, min_matches=100)  # type: ignore[arg-type]

    assert summary.champion_model is None
    assert summary.demoted_versions == 7
    assert summary.promoted_versions == 0
    assert summary.champion_versions == 0
    assert session.committed is True


def test_promote_champion_dry_run_does_not_commit(monkeypatch: Any) -> None:
    monkeypatch.setattr(
        db_champion,
        "champion_model_row",
        lambda _session, min_matches=100: {
            "model": "elo_simple",
            "algorithm": "elo",
            "feature_set_version": "baseline_walk_forward_v1",
            "weighted_rps": 0.2025,
            "matches": 12459,
            "windows": 35,
        },
    )
    session = _FakeSession(
        [
            _FakeResult(rowcount=1),
            _FakeResult(scalars=[11, 22]),
            _FakeResult(rowcount=2),
        ]
    )

    summary = db_champion.promote_champion_by_rps(session, commit=False)  # type: ignore[arg-type]

    assert summary.champion_model == "elo_simple"
    assert summary.champion_versions == 2
    assert session.committed is False

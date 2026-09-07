from __future__ import annotations

from typing import Any

from futpredict.evaluation import db_champion


class _FakeResult:
    def __init__(self, rowcount: int = 0) -> None:
        self.rowcount = rowcount


class _FakeSession:
    """Sesion falsa: solo intercepta _clear_champions y el update de promocion.

    _best_model_per_league y _latest_version_id se mockean, asi que session.execute
    solo se invoca para el clear inicial y el update final.
    """

    def __init__(self, results: list[_FakeResult]) -> None:
        self._results = list(results)
        self.committed = False
        self.calls = 0

    def execute(self, _statement: Any) -> _FakeResult:
        self.calls += 1
        return self._results.pop(0)

    def commit(self) -> None:
        self.committed = True


_PREMIER = {
    "league_id": 1,
    "league_code": "premier-league",
    "model": "market_avg_odds",
    "algorithm": "market_odds",
    "feature_set_version": "baseline_walk_forward_v1",
    "weighted_rps": 0.1956,
    "matches": 12459,
    "windows": 35,
}
_PERU = {
    "league_id": 6,
    "league_code": "liga1-peru",
    "model": "elo_simple",
    "algorithm": "elo",
    "feature_set_version": "baseline_walk_forward_v1",
    "weighted_rps": 0.1986,
    "matches": 1197,
    "windows": 4,
}


def test_promote_champion_marks_best_model_per_league(monkeypatch: Any) -> None:
    monkeypatch.setattr(
        db_champion,
        "_best_model_per_league",
        lambda _session, min_matches=100: [_PREMIER, _PERU],
    )
    monkeypatch.setattr(
        db_champion,
        "_latest_version_id",
        lambda _session, *, league_id, **_kw: {1: 10, 6: 60}[league_id],
    )
    session = _FakeSession(
        [
            _FakeResult(rowcount=6),  # clear champions vigentes
            _FakeResult(rowcount=2),  # promover (una version por liga)
        ]
    )

    summary = db_champion.promote_champion_by_rps(session, min_matches=100)  # type: ignore[arg-type]

    by_league = {c.league_code: c for c in summary.champions}
    assert by_league["premier-league"].model == "market_avg_odds"
    assert by_league["liga1-peru"].model == "elo_simple"
    assert summary.demoted_versions == 6
    assert summary.promoted_versions == 2
    assert summary.champion_versions == 2
    assert by_league["liga1-peru"].weighted_rps == 0.1986
    assert session.committed is True


def test_promote_champion_without_ranked_models_demotes_all(monkeypatch: Any) -> None:
    monkeypatch.setattr(db_champion, "_best_model_per_league", lambda _session, min_matches=100: [])
    session = _FakeSession([_FakeResult(rowcount=7)])  # solo el clear

    summary = db_champion.promote_champion_by_rps(session, min_matches=100)  # type: ignore[arg-type]

    assert summary.champions == []
    assert summary.demoted_versions == 7
    assert summary.promoted_versions == 0
    assert summary.champion_versions == 0
    assert session.committed is True


def test_promote_champion_skips_league_without_version(monkeypatch: Any) -> None:
    # Si _latest_version_id no encuentra version para una liga, esa liga se salta.
    monkeypatch.setattr(
        db_champion,
        "_best_model_per_league",
        lambda _session, min_matches=100: [_PREMIER, _PERU],
    )
    monkeypatch.setattr(
        db_champion,
        "_latest_version_id",
        lambda _session, *, league_id, **_kw: 10 if league_id == 1 else None,
    )
    session = _FakeSession([_FakeResult(rowcount=3), _FakeResult(rowcount=1)])

    summary = db_champion.promote_champion_by_rps(session, min_matches=100)  # type: ignore[arg-type]

    assert [c.league_code for c in summary.champions] == ["premier-league"]
    assert summary.promoted_versions == 1


def test_promote_champion_dry_run_does_not_commit(monkeypatch: Any) -> None:
    monkeypatch.setattr(
        db_champion,
        "_best_model_per_league",
        lambda _session, min_matches=100: [_PERU],
    )
    monkeypatch.setattr(
        db_champion,
        "_latest_version_id",
        lambda _session, *, league_id, **_kw: 60,
    )
    session = _FakeSession([_FakeResult(rowcount=1), _FakeResult(rowcount=1)])

    summary = db_champion.promote_champion_by_rps(session, commit=False)  # type: ignore[arg-type]

    assert [c.league_code for c in summary.champions] == ["liga1-peru"]
    assert summary.champion_versions == 1
    assert session.committed is False

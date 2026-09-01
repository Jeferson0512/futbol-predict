from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from fastapi.testclient import TestClient

from futpredict.domain.fixtures import Fixture
from futpredict.domain.matches import MatchResult
from futpredict.main import create_app


def test_health() -> None:
    client = TestClient(create_app())
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_prediction_history_endpoint(monkeypatch: Any) -> None:
    monkeypatch.setattr(
        "futpredict.api.routes.prediction_history_summary",
        lambda session, model_name, division_codes: {
            "model": model_name,
            "total": 3,
            "evaluated": 2,
            "pending": 1,
            "hits": 1,
            "accuracy": 0.5,
            "avg_rps": 0.2,
        },
    )
    monkeypatch.setattr(
        "futpredict.api.routes.prediction_history_rows",
        lambda session, model_name, division_codes, status, limit: [
            {
                "match_id": 7,
                "kickoff_utc": datetime(2026, 5, 24, 15, 0, tzinfo=UTC),
                "league": "Premier League",
                "home_team": "Villarreal",
                "away_team": "Ath Madrid",
                "status": "finished",
                "home_goals": 5,
                "away_goals": 1,
                "model": model_name,
                "prob_home": 0.6,
                "prob_draw": 0.25,
                "prob_away": 0.15,
                "predicted_outcome": "H",
                "predicted_pick": "Villarreal",
                "actual_outcome": "H",
                "hit": True,
                "rps": 0.12,
            },
            {
                "match_id": 8,
                "kickoff_utc": datetime(2026, 8, 31, 15, 0, tzinfo=UTC),
                "league": "Serie A",
                "home_team": "Lecce",
                "away_team": "Roma",
                "status": "scheduled",
                "home_goals": None,
                "away_goals": None,
                "model": model_name,
                "prob_home": 0.13,
                "prob_draw": 0.23,
                "prob_away": 0.64,
                "predicted_outcome": "A",
                "predicted_pick": "Roma",
                "actual_outcome": None,
                "hit": None,
                "rps": None,
            },
        ],
    )

    client = TestClient(create_app())
    response = client.get("/predictions/history?model=market_avg_odds&limit=10")
    payload = response.json()

    assert response.status_code == 200
    assert payload["summary"]["accuracy"] == 0.5
    assert payload["summary"]["pending"] == 1
    assert len(payload["rows"]) == 2
    assert payload["rows"][0]["hit"] is True
    assert payload["rows"][0]["predicted_pick"] == "Villarreal"
    assert payload["rows"][1]["hit"] is None


def test_match_detail_endpoint(monkeypatch: Any) -> None:
    monkeypatch.setattr(
        "futpredict.api.routes.load_match_detail",
        lambda session, match_id: {
            "match_id": match_id,
            "kickoff_utc": datetime(2026, 5, 24, 15, 0, tzinfo=UTC),
            "league": "Premier League",
            "division": "E0",
            "season": "2526",
            "status": "finished",
            "home_team": "Aston Villa",
            "away_team": "Arsenal",
            "home_goals": 1,
            "away_goals": 2,
            "odds_home": 5.2,
            "odds_draw": 4.3,
            "odds_away": 1.62,
            "implied": [0.16, 0.23, 0.61],
            "home_elo_before": 1712.0,
            "away_elo_before": 1885.0,
            "xg": {
                "home_xg_for_per_match_last_5": 1.3,
                "home_xg_against_per_match_last_5": 1.1,
                "away_xg_for_per_match_last_5": 2.0,
                "away_xg_against_per_match_last_5": 0.8,
            },
            "home_form": ["W", "L", "D", "W", "L"],
            "away_form": ["W", "W", "D", "W", "W"],
            "head_to_head": [
                {
                    "kickoff_utc": datetime(2025, 12, 1, 15, 0, tzinfo=UTC),
                    "home_team": "Arsenal",
                    "away_team": "Aston Villa",
                    "home_goals": 2,
                    "away_goals": 0,
                }
            ],
        },
    )
    client = TestClient(create_app())
    response = client.get("/matches/42")
    payload = response.json()
    assert response.status_code == 200
    assert payload["match_id"] == 42
    assert payload["home_team"] == "Aston Villa"
    assert payload["implied"] == [0.16, 0.23, 0.61]
    assert payload["home_form"] == ["W", "L", "D", "W", "L"]
    assert len(payload["head_to_head"]) == 1


def test_match_detail_not_found(monkeypatch: Any) -> None:
    monkeypatch.setattr(
        "futpredict.api.routes.load_match_detail",
        lambda session, match_id: None,
    )
    client = TestClient(create_app())
    assert client.get("/matches/999").status_code == 404


def test_backtest_endpoint(monkeypatch: Any) -> None:
    monkeypatch.setattr(
        "futpredict.api.routes.load_matches",
        lambda **_: _sample_matches(),
    )

    client = TestClient(create_app())
    response = client.get("/backtests/football-data-uk?season=2526&division=E0")
    payload = response.json()

    assert response.status_code == 200
    assert payload["source"] == "football-data.co.uk"
    assert payload["scope"] == "single_division"
    assert payload["n_matches"] == 2
    assert {item["group_type"] for item in payload["breakdowns"]} == {"division", "season"}
    assert {row["model"] for row in payload["metrics"]} == {
        "always_home",
        "historical_frequency",
        "elo_simple",
    }


def test_big_five_backtest_endpoint(monkeypatch: Any) -> None:
    monkeypatch.setattr(
        "futpredict.api.routes.load_matches",
        lambda **_: _sample_matches(),
    )

    client = TestClient(create_app())
    response = client.get("/backtests/football-data-uk/big-five?start_season=2526&end_season=2526")
    payload = response.json()

    assert response.status_code == 200
    assert payload["scope"] == "big_five"
    assert payload["start_season"] == "2526"
    assert payload["end_season"] == "2526"
    assert payload["divisions"] == ["E0", "SP1", "I1", "D1", "F1"]
    assert any(item["group_key"] == "E0" for item in payload["breakdowns"])


def test_db_big_five_backtest_endpoint(monkeypatch: Any) -> None:
    monkeypatch.setattr(
        "futpredict.api.routes._load_db_matches",
        lambda **_: _sample_matches(),
    )

    client = TestClient(create_app())
    response = client.get("/backtests/db/big-five?start_season=2526&end_season=2526")
    payload = response.json()

    assert response.status_code == 200
    assert payload["source"] == "postgresql:football-data.co.uk"
    assert payload["scope"] == "big_five"
    assert payload["n_matches"] == 2
    assert payload["divisions"] == ["E0", "SP1", "I1", "D1", "F1"]


def test_predictions_status_endpoint(monkeypatch: Any) -> None:
    monkeypatch.setattr(
        "futpredict.api.routes.prediction_status_rows",
        lambda session: [
            {
                "model": "elo_simple",
                "algorithm": "elo",
                "feature_set_version": "baseline_walk_forward_v1",
                "predictions": 10,
                "evaluated": 10,
                "avg_rps": Decimal("0.2"),
                "avg_log_loss": Decimal("1.0"),
                "avg_brier": Decimal("0.6"),
            }
        ],
    )

    client = TestClient(create_app())
    response = client.get("/predictions/status")
    payload = response.json()

    assert response.status_code == 200
    assert payload["rows"][0]["model"] == "elo_simple"
    assert payload["rows"][0]["avg_rps"] == 0.2


def test_calibration_status_endpoint(monkeypatch: Any) -> None:
    monkeypatch.setattr(
        "futpredict.api.routes.calibration_status_rows",
        lambda session, n_bins: [
            {
                "model": "market_avg_odds",
                "algorithm": "market_odds",
                "feature_set_version": "baseline_walk_forward_v1",
                "model_versions": 35,
                "bins": 100,
                "class_samples": 37377,
                "calibration_error": Decimal("0.04"),
            }
        ],
    )

    client = TestClient(create_app())
    response = client.get("/calibration/status?bins=10")
    payload = response.json()

    assert response.status_code == 200
    assert payload["n_bins"] == 10
    assert payload["rows"][0]["calibration_error"] == 0.04


def test_calibration_curves_endpoint(monkeypatch: Any) -> None:
    monkeypatch.setattr(
        "futpredict.api.routes.calibration_curve_rows",
        lambda session, n_bins, model_name: [
            {
                "model": "market_avg_odds",
                "algorithm": "market_odds",
                "feature_set_version": "baseline_walk_forward_v1",
                "outcome": "H",
                "n_bins": 10,
                "bin_index": 4,
                "bin_lower": Decimal("0.4"),
                "bin_upper": Decimal("0.5"),
                "n_predictions": 100,
                "avg_predicted_probability": Decimal("0.45"),
                "observed_frequency": Decimal("0.47"),
                "calibration_error": Decimal("0.02"),
            }
        ],
    )

    client = TestClient(create_app())
    response = client.get("/calibration/curves?bins=10&model=market_avg_odds")
    payload = response.json()

    assert response.status_code == 200
    assert payload["model"] == "market_avg_odds"
    assert payload["rows"][0]["outcome"] == "H"
    assert payload["rows"][0]["observed_frequency"] == 0.47


def test_models_champion_endpoint(monkeypatch: Any) -> None:
    monkeypatch.setattr(
        "futpredict.api.routes.champion_model_row",
        lambda session, min_matches: _ranking_row(),
    )

    client = TestClient(create_app())
    response = client.get("/models/champion")
    payload = response.json()

    assert response.status_code == 200
    assert payload["model"] == "market_avg_odds"
    assert payload["weighted_rps"] == 0.195


def test_upcoming_fixtures_endpoint(monkeypatch: Any) -> None:
    monkeypatch.setattr(
        "futpredict.api.routes.load_upcoming_fixtures_from_db",
        lambda session, start_at, end_at, division_codes, limit: [_sample_fixture()],
    )

    client = TestClient(create_app())
    response = client.get("/fixtures/upcoming?days=7&divisions=E0")
    payload = response.json()

    assert response.status_code == 200
    assert payload["days"] == 7
    assert payload["rows"][0]["home_team"] == "Arsenal"
    assert payload["rows"][0]["avg_home_odds"] == 2.1


def test_fixture_predictions_endpoint(monkeypatch: Any) -> None:
    monkeypatch.setattr(
        "futpredict.api.routes.load_upcoming_fixtures_from_db",
        lambda session, start_at, end_at, division_codes, limit: [_sample_fixture()],
    )
    monkeypatch.setattr(
        "futpredict.api.routes.load_finished_match_results_before_from_db",
        lambda session, cutoff_utc, division_codes: _sample_matches(),
    )
    monkeypatch.setattr(
        "futpredict.api.routes.model_ranking_rows",
        lambda session, min_matches: [_ranking_row()],
    )

    client = TestClient(create_app())
    response = client.get("/fixtures/predictions?days=7&model=best_available")
    payload = response.json()

    assert response.status_code == 200
    assert payload["rows"][0]["fixture"]["away_team"] == "Chelsea"
    assert payload["rows"][0]["predictions"][0]["model"] == "market_avg_odds"
    assert payload["rows"][0]["predictions"][0]["is_recommended"] is True


def _sample_matches() -> list[MatchResult]:
    return [
        MatchResult(
            kickoff_utc=datetime(2025, 8, 15, 20, 0, tzinfo=UTC),
            season="2526",
            division="E0",
            home_team="Liverpool",
            away_team="Bournemouth",
            home_goals=4,
            away_goals=2,
            outcome="H",
        ),
        MatchResult(
            kickoff_utc=datetime(2025, 8, 16, 12, 30, tzinfo=UTC),
            season="2526",
            division="E0",
            home_team="Aston Villa",
            away_team="Newcastle",
            home_goals=0,
            away_goals=0,
            outcome="D",
        ),
    ]


def _sample_fixture() -> Fixture:
    return Fixture(
        match_id=10,
        kickoff_utc=datetime(2026, 8, 30, 14, 0, tzinfo=UTC),
        season="2627",
        division="E0",
        home_team="Arsenal",
        away_team="Chelsea",
        avg_home_odds=2.1,
        avg_draw_odds=3.5,
        avg_away_odds=3.4,
        odds_source="avg",
    )


def _ranking_row() -> dict[str, object]:
    return {
        "model": "market_avg_odds",
        "algorithm": "market_odds",
        "feature_set_version": "baseline_walk_forward_v1",
        "windows": 35,
        "matches": 12459,
        "weighted_rps": Decimal("0.195"),
        "weighted_log_loss": Decimal("0.97"),
        "weighted_brier": Decimal("0.57"),
        "weighted_accuracy": Decimal("0.54"),
        "weighted_calibration_error": Decimal("0.04"),
    }

from __future__ import annotations

from sqlalchemy import UniqueConstraint

from futpredict.db.models import (
    CalibrationBin,
    EloRating,
    Match,
    ModelMetric,
    ModelVersion,
    Odd,
    TeamAlias,
)


def test_matches_have_natural_key_for_ingest_upsert() -> None:
    assert _unique_constraint_names(Match.__table__.constraints) >= {"uq_match_fixture_identity"}


def test_odds_have_natural_key_for_ingest_upsert() -> None:
    assert _unique_constraint_names(Odd.__table__.constraints) >= {"uq_odd_match_bookmaker_market"}


def test_team_aliases_have_source_scoped_natural_keys() -> None:
    assert _unique_constraint_names(TeamAlias.__table__.constraints) >= {
        "uq_team_alias_league_source_canonical",
        "uq_team_alias_team_source_canonical",
    }


def test_elo_ratings_have_team_match_natural_key() -> None:
    assert _unique_constraint_names(EloRating.__table__.constraints) >= {"uq_elo_team_match"}


def test_model_versions_have_walk_forward_identity_key() -> None:
    assert _unique_constraint_names(ModelVersion.__table__.constraints) >= {
        "uq_model_version_identity"
    }


def test_model_metrics_have_version_window_identity_key() -> None:
    assert _unique_constraint_names(ModelMetric.__table__.constraints) >= {
        "uq_model_metric_version_window"
    }


def test_calibration_bins_have_model_outcome_bin_identity_key() -> None:
    assert _unique_constraint_names(CalibrationBin.__table__.constraints) >= {
        "uq_calibration_bin_identity"
    }


def _unique_constraint_names(constraints: set[object]) -> set[str]:
    return {
        constraint.name
        for constraint in constraints
        if isinstance(constraint, UniqueConstraint) and constraint.name is not None
    }

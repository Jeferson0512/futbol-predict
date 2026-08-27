from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class League(Base):
    __tablename__ = "leagues"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True)
    name: Mapped[str] = mapped_column(String(120))
    country: Mapped[str] = mapped_column(String(80))
    tier: Mapped[int] = mapped_column(Integer, default=1)
    source_ids: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class Season(Base):
    __tablename__ = "seasons"
    __table_args__ = (
        UniqueConstraint("league_id", "year_start", "year_end", name="uq_season_league_years"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    league_id: Mapped[int] = mapped_column(ForeignKey("leagues.id"))
    year_start: Mapped[int] = mapped_column(Integer)
    year_end: Mapped[int] = mapped_column(Integer)


class Team(Base):
    __tablename__ = "teams"
    __table_args__ = (
        UniqueConstraint("league_id", "canonical_name", name="uq_team_league_canonical"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    league_id: Mapped[int] = mapped_column(ForeignKey("leagues.id"))
    name: Mapped[str] = mapped_column(String(120))
    canonical_name: Mapped[str] = mapped_column(String(120))
    aliases: Mapped[list[str]] = mapped_column(JSONB, default=list)
    source_ids: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)


class TeamAlias(Base):
    __tablename__ = "team_aliases"
    __table_args__ = (
        UniqueConstraint(
            "league_id",
            "source",
            "canonical_alias",
            name="uq_team_alias_league_source_canonical",
        ),
        UniqueConstraint(
            "team_id",
            "source",
            "canonical_alias",
            name="uq_team_alias_team_source_canonical",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    league_id: Mapped[int] = mapped_column(ForeignKey("leagues.id"))
    team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"))
    source: Mapped[str] = mapped_column(String(80))
    alias: Mapped[str] = mapped_column(String(120))
    canonical_alias: Mapped[str] = mapped_column(String(120))
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Match(Base):
    __tablename__ = "matches"
    __table_args__ = (
        CheckConstraint("home_team_id <> away_team_id", name="ck_match_distinct_teams"),
        UniqueConstraint(
            "league_id",
            "season_id",
            "home_team_id",
            "away_team_id",
            "kickoff_utc",
            name="uq_match_fixture_identity",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    league_id: Mapped[int] = mapped_column(ForeignKey("leagues.id"))
    season_id: Mapped[int] = mapped_column(ForeignKey("seasons.id"))
    home_team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"))
    away_team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"))
    kickoff_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    status: Mapped[str] = mapped_column(String(24))
    home_goals: Mapped[int | None] = mapped_column(Integer)
    away_goals: Mapped[int | None] = mapped_column(Integer)
    home_ht: Mapped[int | None] = mapped_column(Integer)
    away_ht: Mapped[int | None] = mapped_column(Integer)
    home_xg: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))
    away_xg: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))
    shots: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    shots_on_target: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    corners: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    cards: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    raw: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    source: Mapped[str] = mapped_column(String(80))
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Odd(Base):
    __tablename__ = "odds"
    __table_args__ = (
        UniqueConstraint("match_id", "bookmaker", "market", name="uq_odd_match_bookmaker_market"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    match_id: Mapped[int] = mapped_column(ForeignKey("matches.id"))
    bookmaker: Mapped[str] = mapped_column(String(80))
    market: Mapped[str] = mapped_column(String(32))
    odd_home: Mapped[Decimal] = mapped_column(Numeric(10, 4))
    odd_draw: Mapped[Decimal] = mapped_column(Numeric(10, 4))
    odd_away: Mapped[Decimal] = mapped_column(Numeric(10, 4))
    captured_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_closing: Mapped[bool] = mapped_column(Boolean, default=False)


class EloRating(Base):
    __tablename__ = "elo_ratings"
    __table_args__ = (UniqueConstraint("team_id", "match_id", name="uq_elo_team_match"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"))
    match_id: Mapped[int] = mapped_column(ForeignKey("matches.id"))
    rating_before: Mapped[Decimal] = mapped_column(Numeric(9, 3))
    rating_after: Mapped[Decimal] = mapped_column(Numeric(9, 3))
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Feature(Base):
    __tablename__ = "features"

    match_id: Mapped[int] = mapped_column(ForeignKey("matches.id"), primary_key=True)
    feature_set_version: Mapped[str] = mapped_column(String(80), primary_key=True)
    cutoff_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ModelVersion(Base):
    __tablename__ = "model_versions"
    __table_args__ = (
        CheckConstraint("train_window_start < train_window_end", name="ck_model_train_window"),
        UniqueConstraint(
            "league_id",
            "name",
            "algorithm",
            "feature_set_version",
            "train_window_start",
            "train_window_end",
            name="uq_model_version_identity",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    league_id: Mapped[int] = mapped_column(ForeignKey("leagues.id"))
    name: Mapped[str] = mapped_column(String(120))
    algorithm: Mapped[str] = mapped_column(String(80))
    hyperparams: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    trained_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    train_window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    train_window_end: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    feature_set_version: Mapped[str] = mapped_column(String(80))
    artifact_uri: Mapped[str | None] = mapped_column(String(500))
    is_champion: Mapped[bool] = mapped_column(Boolean, default=False)


class Prediction(Base):
    __tablename__ = "predictions"
    __table_args__ = (
        CheckConstraint("predicted_at < kickoff_utc", name="ck_prediction_before_kickoff"),
        CheckConstraint(
            "prob_home >= 0 AND prob_draw >= 0 AND prob_away >= 0",
            name="ck_prediction_probs_nonnegative",
        ),
        CheckConstraint(
            "abs((prob_home + prob_draw + prob_away) - 1.0) <= 0.000001",
            name="ck_prediction_probs_sum_one",
        ),
        UniqueConstraint("match_id", "model_version_id", name="uq_prediction_match_model"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    match_id: Mapped[int] = mapped_column(ForeignKey("matches.id"))
    model_version_id: Mapped[int] = mapped_column(ForeignKey("model_versions.id"))
    kickoff_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    predicted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    prob_home: Mapped[Decimal] = mapped_column(Numeric(10, 8))
    prob_draw: Mapped[Decimal] = mapped_column(Numeric(10, 8))
    prob_away: Mapped[Decimal] = mapped_column(Numeric(10, 8))
    expected_home_goals: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))
    expected_away_goals: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))
    actual_outcome: Mapped[str | None] = mapped_column(String(8))
    rps: Mapped[Decimal | None] = mapped_column(Numeric(10, 8))
    log_loss: Mapped[Decimal | None] = mapped_column(Numeric(10, 8))
    brier: Mapped[Decimal | None] = mapped_column(Numeric(10, 8))


class ModelMetric(Base):
    __tablename__ = "model_metrics"
    __table_args__ = (
        CheckConstraint("n_matches > 0", name="ck_metric_n_matches_positive"),
        UniqueConstraint(
            "model_version_id",
            "window_label",
            name="uq_model_metric_version_window",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    model_version_id: Mapped[int] = mapped_column(ForeignKey("model_versions.id"))
    evaluated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    window_label: Mapped[str] = mapped_column(String(120))
    n_matches: Mapped[int] = mapped_column(Integer)
    rps: Mapped[Decimal] = mapped_column(Numeric(10, 8))
    log_loss: Mapped[Decimal | None] = mapped_column(Numeric(10, 8))
    brier: Mapped[Decimal | None] = mapped_column(Numeric(10, 8))
    accuracy: Mapped[Decimal | None] = mapped_column(Numeric(10, 8))
    calibration_error: Mapped[Decimal | None] = mapped_column(Numeric(10, 8))


class CalibrationBin(Base):
    __tablename__ = "calibration_bins"
    __table_args__ = (
        CheckConstraint("n_bins > 0", name="ck_calibration_n_bins_positive"),
        CheckConstraint(
            "bin_index >= 0 AND bin_index < n_bins",
            name="ck_calibration_bin_index_range",
        ),
        CheckConstraint(
            "bin_lower >= 0 AND bin_upper <= 1 AND bin_lower < bin_upper",
            name="ck_calibration_bin_bounds",
        ),
        CheckConstraint("n_predictions > 0", name="ck_calibration_n_predictions_positive"),
        UniqueConstraint(
            "model_version_id",
            "outcome",
            "n_bins",
            "bin_index",
            name="uq_calibration_bin_identity",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    model_version_id: Mapped[int] = mapped_column(ForeignKey("model_versions.id"))
    evaluated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    outcome: Mapped[str] = mapped_column(String(1))
    n_bins: Mapped[int] = mapped_column(Integer)
    bin_index: Mapped[int] = mapped_column(Integer)
    bin_lower: Mapped[Decimal] = mapped_column(Numeric(10, 8))
    bin_upper: Mapped[Decimal] = mapped_column(Numeric(10, 8))
    n_predictions: Mapped[int] = mapped_column(Integer)
    avg_predicted_probability: Mapped[Decimal] = mapped_column(Numeric(10, 8))
    observed_frequency: Mapped[Decimal] = mapped_column(Numeric(10, 8))
    calibration_error: Mapped[Decimal] = mapped_column(Numeric(10, 8))

"""initial schema

Revision ID: 0001_initial_schema
Revises:
Create Date: 2026-08-25
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0001_initial_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "leagues",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("code", sa.String(length=32), nullable=False, unique=True),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("country", sa.String(length=80), nullable=False),
        sa.Column("tier", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("source_ids", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="{}"),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.create_table(
        "seasons",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("league_id", sa.Integer(), sa.ForeignKey("leagues.id"), nullable=False),
        sa.Column("year_start", sa.Integer(), nullable=False),
        sa.Column("year_end", sa.Integer(), nullable=False),
        sa.UniqueConstraint("league_id", "year_start", "year_end", name="uq_season_league_years"),
    )
    op.create_table(
        "teams",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("league_id", sa.Integer(), sa.ForeignKey("leagues.id"), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("canonical_name", sa.String(length=120), nullable=False),
        sa.Column("aliases", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="[]"),
        sa.Column("source_ids", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="{}"),
        sa.UniqueConstraint("league_id", "canonical_name", name="uq_team_league_canonical"),
    )
    op.create_table(
        "matches",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("league_id", sa.Integer(), sa.ForeignKey("leagues.id"), nullable=False),
        sa.Column("season_id", sa.Integer(), sa.ForeignKey("seasons.id"), nullable=False),
        sa.Column("home_team_id", sa.Integer(), sa.ForeignKey("teams.id"), nullable=False),
        sa.Column("away_team_id", sa.Integer(), sa.ForeignKey("teams.id"), nullable=False),
        sa.Column("kickoff_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("home_goals", sa.Integer(), nullable=True),
        sa.Column("away_goals", sa.Integer(), nullable=True),
        sa.Column("home_ht", sa.Integer(), nullable=True),
        sa.Column("away_ht", sa.Integer(), nullable=True),
        sa.Column("home_xg", sa.Numeric(8, 4), nullable=True),
        sa.Column("away_xg", sa.Numeric(8, 4), nullable=True),
        sa.Column("shots", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="{}"),
        sa.Column("shots_on_target", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="{}"),
        sa.Column("corners", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="{}"),
        sa.Column("cards", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="{}"),
        sa.Column("raw", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="{}"),
        sa.Column("source", sa.String(length=80), nullable=False),
        sa.Column("ingested_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("home_team_id <> away_team_id", name="ck_match_distinct_teams"),
    )
    op.create_index("ix_matches_kickoff_utc", "matches", ["kickoff_utc"])
    op.create_index("ix_matches_league_season", "matches", ["league_id", "season_id"])
    op.create_table(
        "odds",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("match_id", sa.Integer(), sa.ForeignKey("matches.id"), nullable=False),
        sa.Column("bookmaker", sa.String(length=80), nullable=False),
        sa.Column("market", sa.String(length=32), nullable=False),
        sa.Column("odd_home", sa.Numeric(10, 4), nullable=False),
        sa.Column("odd_draw", sa.Numeric(10, 4), nullable=False),
        sa.Column("odd_away", sa.Numeric(10, 4), nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_closing", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_table(
        "elo_ratings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("team_id", sa.Integer(), sa.ForeignKey("teams.id"), nullable=False),
        sa.Column("match_id", sa.Integer(), sa.ForeignKey("matches.id"), nullable=False),
        sa.Column("rating_before", sa.Numeric(9, 3), nullable=False),
        sa.Column("rating_after", sa.Numeric(9, 3), nullable=False),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("team_id", "match_id", name="uq_elo_team_match"),
    )
    op.create_table(
        "features",
        sa.Column("match_id", sa.Integer(), sa.ForeignKey("matches.id"), primary_key=True),
        sa.Column("feature_set_version", sa.String(length=80), primary_key=True),
        sa.Column("cutoff_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_table(
        "model_versions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("league_id", sa.Integer(), sa.ForeignKey("leagues.id"), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("algorithm", sa.String(length=80), nullable=False),
        sa.Column("hyperparams", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="{}"),
        sa.Column("trained_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("train_window_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("train_window_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("feature_set_version", sa.String(length=80), nullable=False),
        sa.Column("artifact_uri", sa.String(length=500), nullable=True),
        sa.Column("is_champion", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.CheckConstraint("train_window_start < train_window_end", name="ck_model_train_window"),
    )
    op.create_index(
        "uq_one_champion_per_league",
        "model_versions",
        ["league_id"],
        unique=True,
        postgresql_where=sa.text("is_champion = true"),
    )
    op.create_table(
        "predictions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("match_id", sa.Integer(), sa.ForeignKey("matches.id"), nullable=False),
        sa.Column("model_version_id", sa.Integer(), sa.ForeignKey("model_versions.id"), nullable=False),
        sa.Column("kickoff_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("predicted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("prob_home", sa.Numeric(10, 8), nullable=False),
        sa.Column("prob_draw", sa.Numeric(10, 8), nullable=False),
        sa.Column("prob_away", sa.Numeric(10, 8), nullable=False),
        sa.Column("expected_home_goals", sa.Numeric(8, 4), nullable=True),
        sa.Column("expected_away_goals", sa.Numeric(8, 4), nullable=True),
        sa.Column("actual_outcome", sa.String(length=8), nullable=True),
        sa.Column("rps", sa.Numeric(10, 8), nullable=True),
        sa.Column("log_loss", sa.Numeric(10, 8), nullable=True),
        sa.Column("brier", sa.Numeric(10, 8), nullable=True),
        sa.CheckConstraint("predicted_at < kickoff_utc", name="ck_prediction_before_kickoff"),
        sa.CheckConstraint("prob_home >= 0 AND prob_draw >= 0 AND prob_away >= 0", name="ck_prediction_probs_nonnegative"),
        sa.CheckConstraint(
            "abs((prob_home + prob_draw + prob_away) - 1.0) <= 0.000001",
            name="ck_prediction_probs_sum_one",
        ),
        sa.UniqueConstraint("match_id", "model_version_id", name="uq_prediction_match_model"),
    )
    op.create_index("ix_predictions_match_model", "predictions", ["match_id", "model_version_id"])
    op.create_table(
        "model_metrics",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("model_version_id", sa.Integer(), sa.ForeignKey("model_versions.id"), nullable=False),
        sa.Column("evaluated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("window_label", sa.String(length=120), nullable=False),
        sa.Column("n_matches", sa.Integer(), nullable=False),
        sa.Column("rps", sa.Numeric(10, 8), nullable=False),
        sa.Column("log_loss", sa.Numeric(10, 8), nullable=True),
        sa.Column("brier", sa.Numeric(10, 8), nullable=True),
        sa.Column("accuracy", sa.Numeric(10, 8), nullable=True),
        sa.Column("calibration_error", sa.Numeric(10, 8), nullable=True),
        sa.CheckConstraint("n_matches > 0", name="ck_metric_n_matches_positive"),
    )


def downgrade() -> None:
    op.drop_table("model_metrics")
    op.drop_index("ix_predictions_match_model", table_name="predictions")
    op.drop_table("predictions")
    op.drop_index("uq_one_champion_per_league", table_name="model_versions")
    op.drop_table("model_versions")
    op.drop_table("features")
    op.drop_table("elo_ratings")
    op.drop_table("odds")
    op.drop_index("ix_matches_league_season", table_name="matches")
    op.drop_index("ix_matches_kickoff_utc", table_name="matches")
    op.drop_table("matches")
    op.drop_table("teams")
    op.drop_table("seasons")
    op.drop_table("leagues")

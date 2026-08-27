"""calibration bins

Revision ID: 0005_calibration_bins
Revises: 0004_model_metric_idempotency
Create Date: 2026-08-26
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0005_calibration_bins"
down_revision = "0004_model_metric_idempotency"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "calibration_bins",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("model_version_id", sa.Integer(), sa.ForeignKey("model_versions.id"), nullable=False),
        sa.Column("evaluated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("outcome", sa.String(length=1), nullable=False),
        sa.Column("n_bins", sa.Integer(), nullable=False),
        sa.Column("bin_index", sa.Integer(), nullable=False),
        sa.Column("bin_lower", sa.Numeric(10, 8), nullable=False),
        sa.Column("bin_upper", sa.Numeric(10, 8), nullable=False),
        sa.Column("n_predictions", sa.Integer(), nullable=False),
        sa.Column("avg_predicted_probability", sa.Numeric(10, 8), nullable=False),
        sa.Column("observed_frequency", sa.Numeric(10, 8), nullable=False),
        sa.Column("calibration_error", sa.Numeric(10, 8), nullable=False),
        sa.CheckConstraint("n_bins > 0", name="ck_calibration_n_bins_positive"),
        sa.CheckConstraint(
            "bin_index >= 0 AND bin_index < n_bins",
            name="ck_calibration_bin_index_range",
        ),
        sa.CheckConstraint(
            "bin_lower >= 0 AND bin_upper <= 1 AND bin_lower < bin_upper",
            name="ck_calibration_bin_bounds",
        ),
        sa.CheckConstraint("n_predictions > 0", name="ck_calibration_n_predictions_positive"),
        sa.UniqueConstraint(
            "model_version_id",
            "outcome",
            "n_bins",
            "bin_index",
            name="uq_calibration_bin_identity",
        ),
    )


def downgrade() -> None:
    op.drop_table("calibration_bins")

"""model metric idempotency

Revision ID: 0004_model_metric_idempotency
Revises: 0003_team_aliases
Create Date: 2026-08-26
"""

from __future__ import annotations

from alembic import op

revision = "0004_model_metric_idempotency"
down_revision = "0003_team_aliases"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_model_version_identity",
        "model_versions",
        [
            "league_id",
            "name",
            "algorithm",
            "feature_set_version",
            "train_window_start",
            "train_window_end",
        ],
    )
    op.create_unique_constraint(
        "uq_model_metric_version_window",
        "model_metrics",
        ["model_version_id", "window_label"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_model_metric_version_window", "model_metrics", type_="unique")
    op.drop_constraint("uq_model_version_identity", "model_versions", type_="unique")

"""natural keys for ingest upserts

Revision ID: 0002_natural_keys_for_ingest
Revises: 0001_initial_schema
Create Date: 2026-08-26
"""

from __future__ import annotations

from alembic import op

revision = "0002_natural_keys_for_ingest"
down_revision = "0001_initial_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_match_fixture_identity",
        "matches",
        ["league_id", "season_id", "home_team_id", "away_team_id", "kickoff_utc"],
    )
    op.create_unique_constraint(
        "uq_odd_match_bookmaker_market",
        "odds",
        ["match_id", "bookmaker", "market"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_odd_match_bookmaker_market", "odds", type_="unique")
    op.drop_constraint("uq_match_fixture_identity", "matches", type_="unique")

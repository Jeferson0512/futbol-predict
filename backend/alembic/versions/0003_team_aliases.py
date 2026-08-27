"""team aliases

Revision ID: 0003_team_aliases
Revises: 0002_natural_keys_for_ingest
Create Date: 2026-08-26
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0003_team_aliases"
down_revision = "0002_natural_keys_for_ingest"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "team_aliases",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("league_id", sa.Integer(), sa.ForeignKey("leagues.id"), nullable=False),
        sa.Column("team_id", sa.Integer(), sa.ForeignKey("teams.id"), nullable=False),
        sa.Column("source", sa.String(length=80), nullable=False),
        sa.Column("alias", sa.String(length=120), nullable=False),
        sa.Column("canonical_alias", sa.String(length=120), nullable=False),
        sa.Column("is_primary", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint(
            "league_id",
            "source",
            "canonical_alias",
            name="uq_team_alias_league_source_canonical",
        ),
        sa.UniqueConstraint(
            "team_id",
            "source",
            "canonical_alias",
            name="uq_team_alias_team_source_canonical",
        ),
    )
    op.create_index("ix_team_aliases_team_id", "team_aliases", ["team_id"])

    op.execute(
        """
        INSERT INTO team_aliases (
            league_id,
            team_id,
            source,
            alias,
            canonical_alias,
            is_primary,
            active,
            created_at
        )
        SELECT
            teams.league_id,
            teams.id,
            'football-data.co.uk',
            aliases.alias,
            lower(regexp_replace(btrim(aliases.alias), '[[:space:]]+', ' ', 'g')),
            aliases.ordinality = 1,
            true,
            now()
        FROM teams
        CROSS JOIN LATERAL jsonb_array_elements_text(teams.aliases)
            WITH ORDINALITY AS aliases(alias, ordinality)
        WHERE btrim(aliases.alias) <> ''
        ON CONFLICT (league_id, source, canonical_alias) DO NOTHING
        """
    )


def downgrade() -> None:
    op.drop_index("ix_team_aliases_team_id", table_name="team_aliases")
    op.drop_table("team_aliases")

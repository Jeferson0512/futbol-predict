"""match fixture identity without kickoff_utc (dedup + merge sources)

La identidad de un partido incluia kickoff_utc, asi que dos fuentes (o ESPN tras
reprogramar) con horas ligeramente distintas creaban filas duplicadas: una
football-data 'scheduled' (sin marcador) y una ESPN 'finished' (con resultado).
Las scheduled fantasma aparecian como "faltantes" en Resultados.

La identidad correcta de un partido de liga es (liga, temporada, local,
visitante): cada enfrentamiento ocurre una vez por temporada. Esta migracion:
1. Deduplica: por cada grupo elige un superviviente (con resultado > sin
   resultado, luego el mas reciente), re-apunta sus predicciones y cuotas al
   superviviente (sin violar constraints) y borra las filas sobrantes (sus
   features/elo se reconstruyen). Asi la prediccion congelada queda ligada al
   partido que si tiene resultado y podra evaluarse.
2. Cambia el unique constraint para quitar kickoff_utc.

Revision ID: 0006_match_natural_key
Revises: 0005_calibration_bins
Create Date: 2026-09-07
"""

from __future__ import annotations

from alembic import op

revision = "0006_match_natural_key"
down_revision = "0005_calibration_bins"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Mapa loser -> survivor por (liga, temporada, local, visitante).
    op.execute(
        """
        CREATE TEMP TABLE _dedup_map AS
        WITH ranked AS (
            SELECT id, league_id, season_id, home_team_id, away_team_id,
                   ROW_NUMBER() OVER (
                       PARTITION BY league_id, season_id, home_team_id, away_team_id
                       ORDER BY (home_goals IS NOT NULL) DESC, kickoff_utc DESC, id DESC
                   ) AS rn
            FROM matches
        ),
        survivors AS (
            SELECT id, league_id, season_id, home_team_id, away_team_id
            FROM ranked WHERE rn = 1
        )
        SELECT r.id AS loser_id, s.id AS survivor_id
        FROM ranked r
        JOIN survivors s
            ON s.league_id = r.league_id AND s.season_id = r.season_id
           AND s.home_team_id = r.home_team_id AND s.away_team_id = r.away_team_id
        WHERE r.rn > 1;
        """
    )

    # 2. Re-apuntar predicciones al superviviente (evitando choque de constraint).
    op.execute(
        """
        UPDATE predictions p SET match_id = d.survivor_id
        FROM _dedup_map d
        WHERE p.match_id = d.loser_id
          AND NOT EXISTS (
              SELECT 1 FROM predictions p2
              WHERE p2.match_id = d.survivor_id
                AND p2.model_version_id = p.model_version_id
          );
        """
    )
    op.execute("DELETE FROM predictions p USING _dedup_map d WHERE p.match_id = d.loser_id;")

    # 3. Re-apuntar cuotas al superviviente (evitando choque de constraint).
    op.execute(
        """
        UPDATE odds o SET match_id = d.survivor_id
        FROM _dedup_map d
        WHERE o.match_id = d.loser_id
          AND NOT EXISTS (
              SELECT 1 FROM odds o2
              WHERE o2.match_id = d.survivor_id
                AND o2.bookmaker = o.bookmaker AND o2.market = o.market
          );
        """
    )
    op.execute("DELETE FROM odds o USING _dedup_map d WHERE o.match_id = d.loser_id;")

    # 4. Features y elo se reconstruyen: basta borrar los de las filas sobrantes.
    op.execute("DELETE FROM features f USING _dedup_map d WHERE f.match_id = d.loser_id;")
    op.execute("DELETE FROM elo_ratings e USING _dedup_map d WHERE e.match_id = d.loser_id;")

    # 5. Borrar las filas duplicadas y el mapa temporal.
    op.execute("DELETE FROM matches m USING _dedup_map d WHERE m.id = d.loser_id;")
    op.execute("DROP TABLE _dedup_map;")

    # 6. Nuevo constraint sin kickoff_utc.
    op.drop_constraint("uq_match_fixture_identity", "matches", type_="unique")
    op.create_unique_constraint(
        "uq_match_fixture_identity",
        "matches",
        ["league_id", "season_id", "home_team_id", "away_team_id"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_match_fixture_identity", "matches", type_="unique")
    op.create_unique_constraint(
        "uq_match_fixture_identity",
        "matches",
        ["league_id", "season_id", "home_team_id", "away_team_id", "kickoff_utc"],
    )

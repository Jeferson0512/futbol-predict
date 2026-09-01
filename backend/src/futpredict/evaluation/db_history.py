"""Historial de predicciones individuales con acierto/fallo.

Alimenta la vista de Resultados: cada prediccion congelada con su pronostico
(argmax de las probabilidades), el resultado real y si acerto, mas un resumen
(porcentaje de acierto y RPS medio) por modelo.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, cast

from sqlalchemy import Select, and_, case, func, select
from sqlalchemy.orm import Session, aliased

from futpredict.data.db_matches import league_codes_from_divisions
from futpredict.db.models import League, Match, ModelVersion, Prediction, Team


def prediction_history_rows(
    session: Session,
    *,
    model_name: str,
    division_codes: Sequence[str] | None = None,
    status: str = "all",
    limit: int = 50,
) -> list[dict[str, object]]:
    home_team = aliased(Team)
    away_team = aliased(Team)
    statement = (
        select(
            Match.id,
            Match.kickoff_utc,
            League.name,
            home_team.name,
            away_team.name,
            Match.status,
            Match.home_goals,
            Match.away_goals,
            ModelVersion.name,
            Prediction.prob_home,
            Prediction.prob_draw,
            Prediction.prob_away,
            Prediction.actual_outcome,
            Prediction.rps,
        )
        .join(ModelVersion, ModelVersion.id == Prediction.model_version_id)
        .join(Match, Match.id == Prediction.match_id)
        .join(League, League.id == Match.league_id)
        .join(home_team, home_team.id == Match.home_team_id)
        .join(away_team, away_team.id == Match.away_team_id)
        .where(ModelVersion.name == model_name)
        .order_by(Match.kickoff_utc.desc(), Match.id.desc())
        .limit(limit)
    )
    statement = _apply_filters(statement, division_codes=division_codes, status=status)

    rows: list[dict[str, object]] = []
    for row in session.execute(statement):
        prob_home = float(row[9])
        prob_draw = float(row[10])
        prob_away = float(row[11])
        predicted = _predicted_outcome(prob_home, prob_draw, prob_away)
        actual = cast("str | None", row[12])
        home_name = cast(str, row[3])
        away_name = cast(str, row[4])
        rows.append(
            {
                "match_id": cast(int, row[0]),
                "kickoff_utc": row[1],
                "league": cast(str, row[2]),
                "home_team": home_name,
                "away_team": away_name,
                "status": cast(str, row[5]),
                "home_goals": cast("int | None", row[6]),
                "away_goals": cast("int | None", row[7]),
                "model": cast(str, row[8]),
                "prob_home": prob_home,
                "prob_draw": prob_draw,
                "prob_away": prob_away,
                "predicted_outcome": predicted,
                "predicted_pick": _pick_label(predicted, home_name, away_name),
                "actual_outcome": actual,
                "hit": None if actual is None else predicted == actual,
                "rps": None if row[13] is None else float(row[13]),
            }
        )
    return rows


def prediction_history_summary(
    session: Session,
    *,
    model_name: str,
    division_codes: Sequence[str] | None = None,
) -> dict[str, object]:
    predicted = case(
        (
            and_(
                Prediction.prob_home >= Prediction.prob_draw,
                Prediction.prob_home >= Prediction.prob_away,
            ),
            "H",
        ),
        (
            and_(
                Prediction.prob_away >= Prediction.prob_home,
                Prediction.prob_away >= Prediction.prob_draw,
            ),
            "A",
        ),
        else_="D",
    )
    hit_expr = case((predicted == Prediction.actual_outcome, 1), else_=0)
    statement = (
        select(
            func.count(Prediction.id).label("total"),
            func.count(Prediction.rps).label("evaluated"),
            func.coalesce(func.sum(hit_expr), 0).label("hits"),
            func.avg(Prediction.rps).label("avg_rps"),
        )
        .join(ModelVersion, ModelVersion.id == Prediction.model_version_id)
        .join(Match, Match.id == Prediction.match_id)
        .join(League, League.id == Match.league_id)
        .where(ModelVersion.name == model_name)
    )
    statement = _apply_filters(statement, division_codes=division_codes, status="all")
    row = session.execute(statement).one()
    total = int(row[0] or 0)
    evaluated = int(row[1] or 0)
    hits = int(row[2] or 0)
    accuracy = hits / evaluated if evaluated else None
    return {
        "model": model_name,
        "total": total,
        "evaluated": evaluated,
        "pending": total - evaluated,
        "hits": hits,
        "accuracy": accuracy,
        "avg_rps": None if row[3] is None else float(row[3]),
    }


def _apply_filters(
    statement: Select[Any],
    *,
    division_codes: Sequence[str] | None,
    status: str,
) -> Select[Any]:
    league_codes = league_codes_from_divisions(division_codes)
    if league_codes:
        statement = statement.where(League.code.in_(league_codes))
    if status == "evaluated":
        statement = statement.where(Prediction.rps.is_not(None))
    elif status == "pending":
        statement = statement.where(Prediction.rps.is_(None))
    return statement


def _predicted_outcome(prob_home: float, prob_draw: float, prob_away: float) -> str:
    if prob_home >= prob_draw and prob_home >= prob_away:
        return "H"
    if prob_away >= prob_home and prob_away >= prob_draw:
        return "A"
    return "D"


def _pick_label(outcome: str, home_team: str, away_team: str) -> str:
    if outcome == "H":
        return home_team
    if outcome == "A":
        return away_team
    return "Empate"

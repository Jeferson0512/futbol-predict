"""Persistencia de xG de Understat en la tabla matches.

Empareja cada partido de Understat con el nuestro por (temporada, equipos
normalizados) y escribe `home_xg`/`away_xg`. El emparejamiento por nombre
normalizado es seguro porque cada cruce local-visitante ocurre una vez por
temporada en liga.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import update
from sqlalchemy.orm import Session

from futpredict.db.models import Match
from futpredict.domain.matches import MatchResult
from futpredict.ingest.providers.understat import UnderstatMatchXg, normalize_team


@dataclass(frozen=True)
class UnderstatStoreSummary:
    understat_matches: int
    db_matches: int
    updated: int
    unmatched: int


def store_understat_xg(
    session: Session,
    understat_matches: Sequence[UnderstatMatchXg],
    our_matches: Sequence[MatchResult],
    *,
    commit: bool = True,
) -> UnderstatStoreSummary:
    key_to_id: dict[tuple[str, str], int] = {}
    for match in our_matches:
        if match.match_id is None:
            continue
        key_to_id[(normalize_team(match.home_team), normalize_team(match.away_team))] = (
            match.match_id
        )

    updated = 0
    for understat in understat_matches:
        key = (normalize_team(understat.home_team), normalize_team(understat.away_team))
        match_id = key_to_id.get(key)
        if match_id is None:
            continue
        session.execute(
            update(Match)
            .where(Match.id == match_id)
            .values(
                home_xg=_xg_decimal(understat.home_xg),
                away_xg=_xg_decimal(understat.away_xg),
            )
        )
        updated += 1

    if commit:
        session.commit()

    return UnderstatStoreSummary(
        understat_matches=len(understat_matches),
        db_matches=len(our_matches),
        updated=updated,
        unmatched=len(understat_matches) - updated,
    )


def _xg_decimal(value: float) -> Decimal:
    return Decimal(str(round(value, 4)))

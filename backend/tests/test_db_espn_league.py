from __future__ import annotations

from futpredict.data.db_espn_league import ARGENTINA, BRAZIL, ESPN_LEAGUES


def test_espn_league_configs_map_to_espn_slugs() -> None:
    assert BRAZIL.division == "BRA1"
    assert BRAZIL.slug == "bra.1"
    assert BRAZIL.league_code == "brasileirao"
    assert ARGENTINA.division == "ARG1"
    assert ARGENTINA.slug == "arg.1"
    assert ARGENTINA.league_code == "liga-argentina"


def test_espn_leagues_registry() -> None:
    assert set(ESPN_LEAGUES) == {"brazil", "argentina"}
    assert ESPN_LEAGUES["brazil"] is BRAZIL
    assert ESPN_LEAGUES["argentina"] is ARGENTINA

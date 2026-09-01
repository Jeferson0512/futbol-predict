from __future__ import annotations

from datetime import date

import pytest

from futpredict.data.db_matches import (
    division_code_for_league,
    league_codes_from_divisions,
    season_code_from_years,
)
from futpredict.data.football_data_uk_catalog import (
    DIVISIONS_BY_CODE,
    big_five_division_codes,
    current_season_code,
    division_for_league_code,
    season_range,
    season_years,
)
from futpredict.db.models import League


def test_season_range_is_inclusive() -> None:
    assert season_range("2122", "2324") == ["2122", "2223", "2324"]


def test_season_range_rejects_reversed_range() -> None:
    with pytest.raises(ValueError, match="end season"):
        season_range("2324", "2122")


def test_big_five_division_codes() -> None:
    assert big_five_division_codes() == ["E0", "SP1", "I1", "D1", "F1"]


def test_season_years_expands_football_data_code() -> None:
    assert season_years("2526") == (2025, 2026)
    assert season_years("9900") == (1999, 2000)


def test_current_season_code_rolls_over_in_july() -> None:
    assert current_season_code(date(2026, 6, 30)) == "2526"
    assert current_season_code(date(2026, 7, 1)) == "2627"


def test_peru_division_registered_without_polluting_big_five() -> None:
    # PER1 se resuelve, pero big_five_division_codes sigue siendo solo los 5.
    assert "PER1" in DIVISIONS_BY_CODE
    assert "PER1" not in big_five_division_codes()
    assert league_codes_from_divisions(["PER1"]) == ["liga1-peru"]
    assert division_for_league_code("liga1-peru") == "PER1"
    assert division_for_league_code("desconocida") is None


def test_division_code_for_league_maps_peru() -> None:
    peru = League(code="liga1-peru", name="Liga 1 Peru", country="Peru", source_ids={})
    assert division_code_for_league(peru) == "PER1"


def test_season_code_handles_calendar_year_leagues() -> None:
    assert season_code_from_years(2025, 2026) == "2526"  # Big-5 (ago-may)
    assert season_code_from_years(2026, 2026) == "2026"  # Liga 1 Peru (ano calendario)

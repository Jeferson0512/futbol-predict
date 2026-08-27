from __future__ import annotations

from datetime import date

import pytest

from futpredict.data.football_data_uk_catalog import (
    big_five_division_codes,
    current_season_code,
    season_range,
    season_years,
)


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

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from futpredict.features.guards import FeatureInput, assert_no_leakage


def test_guard_accepts_inputs_before_cutoff() -> None:
    cutoff = datetime(2026, 8, 25, 20, 0, tzinfo=UTC)
    inputs = [
        FeatureInput(name="last_match_xg", observed_at=datetime(2026, 8, 20, tzinfo=UTC))
    ]
    assert_no_leakage(inputs, cutoff)


def test_guard_rejects_inputs_at_or_after_cutoff() -> None:
    cutoff = datetime(2026, 8, 25, 20, 0, tzinfo=UTC)
    inputs = [FeatureInput(name="final_table_position", observed_at=cutoff)]
    with pytest.raises(ValueError, match="feature leakage detected"):
        assert_no_leakage(inputs, cutoff)

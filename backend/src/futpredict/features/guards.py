from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class FeatureInput:
    name: str
    observed_at: datetime


def assert_no_leakage(inputs: list[FeatureInput], cutoff_utc: datetime) -> None:
    leaked = [item for item in inputs if item.observed_at >= cutoff_utc]
    if leaked:
        names = ", ".join(item.name for item in leaked)
        msg = f"feature leakage detected at cutoff {cutoff_utc.isoformat()}: {names}"
        raise ValueError(msg)

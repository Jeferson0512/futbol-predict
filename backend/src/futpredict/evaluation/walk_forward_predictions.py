from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime

from futpredict.data.football_data_uk_catalog import season_range
from futpredict.domain.matches import MatchResult
from futpredict.evaluation.backtest import (
    PredictionProvider,
    PredictionRow,
    run_baseline_backtest,
)
from futpredict.evaluation.walk_forward import DEFAULT_INITIAL_TRAIN_SEASONS


@dataclass(frozen=True)
class WalkForwardPrediction:
    division: str
    evaluation_season: str
    train_start_season: str
    train_end_season: str
    train_window_start_utc: datetime
    train_window_end_utc: datetime
    eval_window_start_utc: datetime
    eval_window_end_utc: datetime
    prediction: PredictionRow

    @property
    def window_label(self) -> str:
        return (
            f"eval_{self.evaluation_season}_"
            f"train_{self.train_start_season}_{self.train_end_season}"
        )


def run_expanding_walk_forward_predictions(
    matches: Iterable[MatchResult],
    *,
    start_season: str,
    end_season: str,
    initial_train_seasons: int = DEFAULT_INITIAL_TRAIN_SEASONS,
    extra_prediction_providers: Sequence[PredictionProvider] | None = None,
) -> list[WalkForwardPrediction]:
    seasons = season_range(start_season, end_season)
    if initial_train_seasons < 1:
        msg = "initial_train_seasons must be positive"
        raise ValueError(msg)
    if len(seasons) <= initial_train_seasons:
        msg = "season range must leave at least one evaluation season"
        raise ValueError(msg)

    materialized = [match for match in matches if match.season in set(seasons)]
    by_division: dict[str, list[MatchResult]] = {}
    for match in materialized:
        by_division.setdefault(match.division, []).append(match)

    predictions: list[WalkForwardPrediction] = []
    for division, division_matches in sorted(by_division.items()):
        ordered_division_matches = sorted(division_matches, key=lambda match: match.kickoff_utc)
        for eval_index in range(initial_train_seasons, len(seasons)):
            train_seasons = set(seasons[:eval_index])
            eval_season = seasons[eval_index]
            train_matches = [
                match for match in ordered_division_matches if match.season in train_seasons
            ]
            eval_matches = [
                match for match in ordered_division_matches if match.season == eval_season
            ]
            if not train_matches or not eval_matches:
                continue

            prediction_rows = run_baseline_backtest(
                [*train_matches, *eval_matches],
                isolate_by_division=False,
                extra_prediction_providers=extra_prediction_providers,
            )
            eval_rows = [row for row in prediction_rows if row.match.season == eval_season]
            for row in eval_rows:
                predictions.append(
                    WalkForwardPrediction(
                        division=division,
                        evaluation_season=eval_season,
                        train_start_season=seasons[0],
                        train_end_season=seasons[eval_index - 1],
                        train_window_start_utc=train_matches[0].kickoff_utc,
                        train_window_end_utc=train_matches[-1].kickoff_utc,
                        eval_window_start_utc=eval_matches[0].kickoff_utc,
                        eval_window_end_utc=eval_matches[-1].kickoff_utc,
                        prediction=row,
                    )
                )

    return predictions

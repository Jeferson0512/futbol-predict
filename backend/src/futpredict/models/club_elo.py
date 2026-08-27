from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

from futpredict.domain.matches import MatchResult
from futpredict.evaluation.backtest import PredictionRow
from futpredict.ingest.providers.clubelo import (
    DEFAULT_CACHE_DIR,
    ClubEloHistoryLoad,
    ClubEloTeamHistory,
    HistoryProgressCallback,
    load_team_histories,
)
from futpredict.models.elo import expected_home_score

CLUB_ELO_MODEL_NAME = "club_elo"


@dataclass(frozen=True)
class ClubEloPredictionConfig:
    home_advantage: float = 65.0
    draw_probability: float = 0.26
    lookup_lag_days: int = 1


@dataclass(frozen=True)
class ClubEloPredictionCoverage:
    total_matches: int
    predicted_matches: int
    skipped_matches: int
    missing_team_names: tuple[str, ...]

    @property
    def coverage_ratio(self) -> float:
        if self.total_matches == 0:
            return 0.0
        return self.predicted_matches / self.total_matches


class ClubEloPredictor:
    def __init__(
        self,
        histories_by_team: dict[str, ClubEloTeamHistory],
        *,
        config: ClubEloPredictionConfig | None = None,
    ) -> None:
        self._histories_by_team = histories_by_team
        self._config = config or ClubEloPredictionConfig()

    def __call__(self, match: MatchResult) -> PredictionRow | None:
        probabilities = self.predict_probabilities(match)
        if probabilities is None:
            return None
        return PredictionRow(CLUB_ELO_MODEL_NAME, match, probabilities)

    def predict_probabilities(self, match: MatchResult) -> tuple[float, float, float] | None:
        home_history = self._histories_by_team.get(match.home_team)
        away_history = self._histories_by_team.get(match.away_team)
        if home_history is None or away_history is None:
            return None

        lookup_date = match.kickoff_utc.date() - timedelta(days=self._config.lookup_lag_days)
        home_rating = home_history.rating_on(lookup_date)
        away_rating = away_history.rating_on(lookup_date)
        if home_rating is None or away_rating is None:
            return None

        home_expected = expected_home_score(
            home_rating,
            away_rating,
            self._config.home_advantage,
        )
        draw_probability = self._config.draw_probability
        decisive_probability = 1.0 - draw_probability
        return (
            home_expected * decisive_probability,
            draw_probability,
            (1.0 - home_expected) * decisive_probability,
        )

    def coverage_for_matches(self, matches: list[MatchResult]) -> ClubEloPredictionCoverage:
        predicted = sum(1 for match in matches if self.predict_probabilities(match) is not None)
        return ClubEloPredictionCoverage(
            total_matches=len(matches),
            predicted_matches=predicted,
            skipped_matches=len(matches) - predicted,
            missing_team_names=tuple(
                sorted(
                    {
                        team_name
                        for match in matches
                        for team_name in (match.home_team, match.away_team)
                        if team_name not in self._histories_by_team
                    }
                )
            ),
        )


def load_club_elo_predictor_for_matches(
    matches: list[MatchResult],
    *,
    cache_dir: Path | str = DEFAULT_CACHE_DIR,
    force: bool = False,
    timeout: float = 30.0,
    max_workers: int = 6,
    allow_download: bool = True,
    progress_callback: HistoryProgressCallback | None = None,
) -> tuple[ClubEloPredictor, ClubEloHistoryLoad]:
    team_names = {match.home_team for match in matches} | {match.away_team for match in matches}
    history_load = load_team_histories(
        team_names,
        cache_dir=cache_dir,
        force=force,
        timeout=timeout,
        max_workers=max_workers,
        allow_download=allow_download,
        progress_callback=progress_callback,
    )
    return ClubEloPredictor(history_load.histories_by_team), history_load

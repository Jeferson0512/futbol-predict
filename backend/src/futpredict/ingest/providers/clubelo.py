from __future__ import annotations

import csv
import re
import unicodedata
from bisect import bisect_right
from collections.abc import Callable, Iterable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import date
from io import StringIO
from pathlib import Path

import httpx

BASE_URL = "http://api.clubelo.com"
DEFAULT_CACHE_DIR = Path("data/raw/clubelo")
SOURCE_NAME = "clubelo"

CSV_HEADER = ("Rank", "Club", "Country", "Level", "Elo", "From", "To")
HistoryProgressCallback = Callable[[int, int, str, bool], None]

TEAM_API_NAME_OVERRIDES: dict[str, tuple[str, ...]] = {
    "Ath Bilbao": ("Bilbao", "Athletic", "AthleticClub"),
    "Ath Madrid": ("Atletico", "AtleticoMadrid"),
    "Bayern Munich": ("Bayern", "BayernMunich"),
    "Ein Frankfurt": ("Frankfurt", "EintrachtFrankfurt"),
    "Espanol": ("Espanyol",),
    "FC Koln": ("Koeln", "Koln", "FCKoeln"),
    "Fortuna Dusseldorf": ("Duesseldorf", "Dusseldorf", "FortunaDuesseldorf"),
    "Greuther Furth": ("Fuerth", "GreutherFuerth", "GreutherFurth"),
    "Holstein Kiel": ("Holstein", "HolsteinKiel"),
    "La Coruna": ("Depor", "LaCoruna", "Deportivo"),
    "Las Palmas": ("LasPalmas",),
    "Le Havre": ("LeHavre",),
    "M'gladbach": ("Gladbach", "Mgladbach", "Moenchengladbach"),
    "Man City": ("ManCity",),
    "Man United": ("ManUnited",),
    "Nott'm Forest": ("Forest", "NottinghamForest", "NottmForest"),
    "Nurnberg": ("Nuernberg",),
    "Paris FC": ("ParisFC",),
    "Paris SG": ("ParisSG",),
    "RB Leipzig": ("RBLeipzig",),
    "Real Madrid": ("RealMadrid",),
    "Schalke 04": ("Schalke", "Schalke04"),
    "Sociedad": ("RealSociedad", "Sociedad"),
    "Sp Gijon": ("Gijon", "SportingGijon"),
    "Spal": ("SPAL", "Spal"),
    "St Etienne": ("Saint-Etienne", "StEtienne"),
    "St Pauli": ("StPauli",),
    "Union Berlin": ("UnionBerlin",),
    "Vallecano": ("RayoVallecano",),
    "Werder Bremen": ("Werder", "WerderBremen"),
    "West Brom": ("WestBrom",),
    "West Ham": ("WestHam",),
}


@dataclass(frozen=True)
class ClubEloRatingPeriod:
    club: str
    country: str
    level: int | None
    elo: float
    from_date: date
    to_date: date


@dataclass(frozen=True)
class ClubEloTeamHistory:
    source_team_name: str
    api_name: str
    display_name: str
    periods: tuple[ClubEloRatingPeriod, ...]
    _from_dates: tuple[date, ...] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "_from_dates", tuple(period.from_date for period in self.periods))

    def rating_on(self, lookup_date: date) -> float | None:
        index = bisect_right(self._from_dates, lookup_date) - 1
        if index < 0:
            return None
        period = self.periods[index]
        if period.from_date <= lookup_date <= period.to_date:
            return period.elo
        return None


@dataclass(frozen=True)
class ClubEloHistoryLoad:
    histories_by_team: dict[str, ClubEloTeamHistory]
    missing_team_names: tuple[str, ...]

    @property
    def loaded_teams(self) -> int:
        return len(self.histories_by_team)

    @property
    def missing_teams(self) -> int:
        return len(self.missing_team_names)


def api_name_candidates(
    team_name: str,
    api_name_overrides: Mapping[str, Sequence[str]] | None = None,
) -> tuple[str, ...]:
    overrides = api_name_overrides or TEAM_API_NAME_OVERRIDES
    candidates: list[str] = []
    candidates.extend(overrides.get(team_name, ()))

    ascii_name = ascii_fold(team_name)
    variants = (
        ascii_name,
        ascii_name.replace("&", "and"),
        re.sub(r"\bFC\b", "", ascii_name).strip(),
        re.sub(r"\bAFC\b", "", ascii_name).strip(),
    )
    for variant in variants:
        compact = re.sub(r"[^A-Za-z0-9-]", "", variant)
        if compact:
            candidates.append(compact)

    return tuple(dict.fromkeys(candidates))


def ascii_fold(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    return normalized.encode("ascii", "ignore").decode("ascii")


def team_history_cache_path(
    api_name: str,
    cache_dir: Path | str = DEFAULT_CACHE_DIR,
) -> Path:
    safe_name = re.sub(r"[^A-Za-z0-9-]", "", api_name)
    return Path(cache_dir) / f"{safe_name}.csv"


def download_team_history_text(
    api_name: str,
    *,
    base_url: str = BASE_URL,
    timeout: float = 30.0,
) -> str:
    url = f"{base_url.rstrip('/')}/{api_name}"
    response = httpx.get(url, timeout=timeout)
    response.raise_for_status()
    return response.text


def load_team_history(
    team_name: str,
    *,
    cache_dir: Path | str = DEFAULT_CACHE_DIR,
    force: bool = False,
    timeout: float = 30.0,
    allow_download: bool = True,
    api_name_overrides: Mapping[str, Sequence[str]] | None = None,
) -> ClubEloTeamHistory | None:
    for api_name in api_name_candidates(team_name, api_name_overrides):
        path = team_history_cache_path(api_name, cache_dir)
        if path.exists() and not force:
            history = parse_team_history_csv(
                path.read_text(encoding="utf-8"),
                source_team_name=team_name,
                api_name=api_name,
            )
            if history.periods:
                return history

        if not allow_download:
            continue

        try:
            text = download_team_history_text(api_name, timeout=timeout)
            history = parse_team_history_csv(
                text,
                source_team_name=team_name,
                api_name=api_name,
            )
        except httpx.TimeoutException:
            continue
        except (httpx.HTTPStatusError, ValueError):
            continue
        if history.periods:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
            return history

    return None


def load_team_histories(
    team_names: Iterable[str],
    *,
    cache_dir: Path | str = DEFAULT_CACHE_DIR,
    force: bool = False,
    timeout: float = 30.0,
    max_workers: int = 6,
    allow_download: bool = True,
    progress_callback: HistoryProgressCallback | None = None,
    api_name_overrides: Mapping[str, Sequence[str]] | None = None,
) -> ClubEloHistoryLoad:
    histories: dict[str, ClubEloTeamHistory] = {}
    missing: list[str] = []
    unique_team_names = sorted(set(team_names))
    if max_workers <= 1:
        total = len(unique_team_names)
        for done, team_name in enumerate(unique_team_names, start=1):
            history = load_team_history(
                team_name,
                cache_dir=cache_dir,
                force=force,
                timeout=timeout,
                allow_download=allow_download,
                api_name_overrides=api_name_overrides,
            )
            if history is None:
                missing.append(team_name)
                loaded = False
            else:
                histories[team_name] = history
                loaded = True
            if progress_callback is not None:
                progress_callback(done, total, team_name, loaded)
        return ClubEloHistoryLoad(histories_by_team=histories, missing_team_names=tuple(missing))

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        total = len(unique_team_names)
        future_by_team = {
            executor.submit(
                load_team_history,
                team_name,
                cache_dir=cache_dir,
                force=force,
                timeout=timeout,
                allow_download=allow_download,
                api_name_overrides=api_name_overrides,
            ): team_name
            for team_name in unique_team_names
        }
        for done, future in enumerate(as_completed(future_by_team), start=1):
            team_name = future_by_team[future]
            history = future.result()
            if history is None:
                missing.append(team_name)
                loaded = False
            else:
                histories[team_name] = history
                loaded = True
            if progress_callback is not None:
                progress_callback(done, total, team_name, loaded)

    return ClubEloHistoryLoad(
        histories_by_team=histories,
        missing_team_names=tuple(sorted(missing)),
    )


def parse_team_history_csv(
    text: str,
    *,
    source_team_name: str,
    api_name: str,
) -> ClubEloTeamHistory:
    reader = csv.DictReader(StringIO(text))
    fieldnames = tuple(reader.fieldnames or ())
    missing_columns = sorted(set(CSV_HEADER) - set(fieldnames))
    if missing_columns:
        msg = f"ClubElo CSV missing required columns: {missing_columns}"
        raise ValueError(msg)

    periods: list[ClubEloRatingPeriod] = []
    for row in reader:
        elo_text = (row.get("Elo") or "").strip()
        from_text = (row.get("From") or "").strip()
        to_text = (row.get("To") or "").strip()
        if not elo_text or elo_text == "None" or not from_text or not to_text:
            continue
        periods.append(
            ClubEloRatingPeriod(
                club=(row.get("Club") or source_team_name).strip(),
                country=(row.get("Country") or "").strip(),
                level=_optional_int(row.get("Level")),
                elo=float(elo_text),
                from_date=date.fromisoformat(from_text),
                to_date=date.fromisoformat(to_text),
            )
        )

    ordered = tuple(sorted(periods, key=lambda period: period.from_date))
    display_name = ordered[-1].club if ordered else source_team_name
    return ClubEloTeamHistory(
        source_team_name=source_team_name,
        api_name=api_name,
        display_name=display_name,
        periods=ordered,
    )


def _optional_int(value: str | None) -> int | None:
    if value is None:
        return None
    stripped = value.strip()
    if not stripped or stripped == "None":
        return None
    return int(stripped)

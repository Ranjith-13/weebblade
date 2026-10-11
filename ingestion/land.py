"""Fetch one source's seasons and land them, raw and processed.

This was four near-identical task bodies in the weekly DAG - same loop, same
comments, same order of operations, differing only in which module to import and
which directory to write to. That was tolerable while Airflow was the only way
to run the pipeline. It stopped being tolerable the moment a second entrypoint
existed (pipeline/run.py), because then the same eight lines would have been
written twice more and been free to drift apart in either copy.

Every source here exposes the same two things - fetch_season.fetch_season and
transform.flatten_media - which is what makes one function enough. A source that
does not fit that shape does not belong in SOURCES; it belongs in its own task.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from importlib import import_module
from pathlib import Path
from typing import Any

from .seasons import capture_both
from .storage import write_parquet, write_raw_json
from .validate import validate_rows

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Source:
    """Where a source's code lives and where its data goes.

    `label` is only for the log line, where "AniList" reads better than the key.
    """

    package: str
    label: str


SOURCES: dict[str, Source] = {
    "anilist": Source("ingestion.anilist", "AniList"),
    "jikan": Source("ingestion.jikan", "Jikan"),
    "mal": Source("ingestion.mal", "MAL"),
    "kitsu": Source("ingestion.kitsu", "Kitsu"),
}


def land_season(source: str, at: Any, data_dir: Path) -> int:
    """Land this season and the next one for `source`, returning rows written.

    Both seasons, because the sources list a season months before it airs and
    fetching only the running one left the catalogue with no Fall 2026 title nine
    days before Fall 2026 began (see ingestion/seasons.capture_both).

    `at` is the end of the interval being captured - Airflow's data_interval_end,
    or simply now for a run started by hand. Never a logical_date: that is the
    start of the interval, and it would file today's fetch under last week.

    MAL alone can refuse for a reason that is a configuration choice rather than
    a failure: no client id. That skips the source cleanly, here as in the DAG,
    so an installation that has never registered one still gets a green run.
    """
    spec = SOURCES[source]
    fetch_season = import_module(f"{spec.package}.fetch_season").fetch_season
    flatten_media = import_module(f"{spec.package}.transform").flatten_media
    from .mal.client import MissingClientId

    written = 0
    for season, season_year, run_date, partition in capture_both(at):
        try:
            raw = fetch_season(season, season_year)
        except MissingClientId as exc:
            # The same for both seasons, so say it once and leave.
            logger.warning("Skipping %s: %s", spec.label, exc)
            return written

        logger.info("%s: fetched %s titles for %s %s", spec.label, len(raw), season, season_year)
        write_raw_json(raw, data_dir / "raw" / source / partition, run_date)

        rows = [flatten_media(media) for media in raw]
        # Between flattening and writing: the boundary where this source's own
        # vocabulary and units are supposed to have become this project's, and
        # the only place a scale or vocabulary error is still cheap to catch.
        validate_rows(rows, source)
        write_parquet(rows, data_dir / "processed" / f"{source}_media" / partition, run_date)
        written += len(rows)

    return written

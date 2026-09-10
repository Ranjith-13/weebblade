from __future__ import annotations

import logging
from pathlib import Path

import pendulum
from airflow.decorators import dag, task
from airflow.utils.trigger_rule import TriggerRule

from ingestion.seasons import capture_for
from ingestion.validate import validate_rows
from ingestion.storage import write_parquet, write_raw_json

logger = logging.getLogger(__name__)

# Not /opt/airflow/data: DuckDB bakes this absolute path into each view's SQL at
# CREATE VIEW time (processing/duckdb_catalog.py), and the backend container - which
# opens the same warehouse.duckdb file over its own bind mount - needs to see the
# data directory at this exact same path for those views to resolve there too.
DATA_DIR = Path("/data")


@dag(
    dag_id="anime_seasonal_pipeline",
    schedule="@weekly",
    start_date=pendulum.datetime(2026, 1, 1, tz="UTC"),
    catchup=False,
    tags=["ingestion", "processing", "anime"],
)
def anime_seasonal_pipeline():
    # One task per source, deliberately not chained together: if one API is down (as
    # AniList and Jikan currently are) the others should still land data rather than
    # the whole DAG run blocking on it.

    @task
    def fetch_anilist(data_interval_end=None):
        from ingestion.anilist.fetch_season import fetch_season
        from ingestion.anilist.transform import flatten_media

        season, season_year, run_date, partition = capture_for(data_interval_end)

        raw = fetch_season(season, season_year)
        logger.info("AniList: fetched %s titles", len(raw))
        write_raw_json(raw, DATA_DIR / "raw" / "anilist" / partition, run_date)
        rows = [flatten_media(m) for m in raw]
        # Between flattening and writing: the boundary where this source's own
        # vocabulary and units are supposed to have become this project's, and the
        # only place a scale or vocabulary error is still cheap to catch.
        validate_rows(rows, "anilist")
        write_parquet(rows, DATA_DIR / "processed" / "anilist_media" / partition, run_date)

    @task
    def fetch_jikan(data_interval_end=None):
        from ingestion.jikan.fetch_season import fetch_season
        from ingestion.jikan.transform import flatten_media

        season, season_year, run_date, partition = capture_for(data_interval_end)

        raw = fetch_season(season, season_year)
        logger.info("Jikan: fetched %s titles", len(raw))
        write_raw_json(raw, DATA_DIR / "raw" / "jikan" / partition, run_date)
        rows = [flatten_media(m) for m in raw]
        # Between flattening and writing: the boundary where this source's own
        # vocabulary and units are supposed to have become this project's, and the
        # only place a scale or vocabulary error is still cheap to catch.
        validate_rows(rows, "jikan")
        write_parquet(rows, DATA_DIR / "processed" / "jikan_media" / partition, run_date)

    @task
    def fetch_mal(data_interval_end=None):
        """The OFFICIAL MyAnimeList API v2, not the Jikan mirror.

        Jikan has returned 504 ("MyAnimeList may be down") for this project's
        whole life, but MAL itself answers 200 and api.myanimelist.net returns a
        well-formed "Invalid client id" - verified, not assumed. MAL was never
        the broken part; Jikan was. This source exists because MAL carries the
        two columns that are null for 100% of stored rows, studios and
        source_material, plus scores for titles Kitsu does not rate.

        Skips cleanly when MAL_CLIENT_ID is unset so the DAG stays green on an
        installation that has not registered one, rather than failing a task for
        a configuration choice.
        """
        from ingestion.mal.client import MissingClientId
        from ingestion.mal.fetch_season import fetch_season
        from ingestion.mal.transform import flatten_media

        season, season_year, run_date, partition = capture_for(data_interval_end)

        try:
            raw = fetch_season(season, season_year)
        except MissingClientId as exc:
            logger.warning("Skipping MAL: %s", exc)
            return

        logger.info("MAL: fetched %s titles", len(raw))
        write_raw_json(raw, DATA_DIR / "raw" / "mal" / partition, run_date)
        rows = [flatten_media(m) for m in raw]
        # Between flattening and writing: the boundary where this source's own
        # vocabulary and units are supposed to have become this project's, and the
        # only place a scale or vocabulary error is still cheap to catch.
        validate_rows(rows, "mal")
        write_parquet(rows, DATA_DIR / "processed" / "mal_media" / partition, run_date)

    @task
    def fetch_kitsu(data_interval_end=None):
        from ingestion.kitsu.fetch_season import fetch_season
        from ingestion.kitsu.transform import flatten_media

        season, season_year, run_date, partition = capture_for(data_interval_end)

        raw = fetch_season(season, season_year)
        logger.info("Kitsu: fetched %s titles", len(raw))
        write_raw_json(raw, DATA_DIR / "raw" / "kitsu" / partition, run_date)
        rows = [flatten_media(m) for m in raw]
        # Between flattening and writing: the boundary where this source's own
        # vocabulary and units are supposed to have become this project's, and the
        # only place a scale or vocabulary error is still cheap to catch.
        validate_rows(rows, "kitsu")
        write_parquet(rows, DATA_DIR / "processed" / "kitsu_media" / partition, run_date)

    # trigger_rule=ALL_DONE: run even if some (or all but one) of the fetch tasks
    # above failed - consolidate whatever snapshots actually landed rather than
    # blocking the whole pipeline on every source being healthy at once.
    @task(trigger_rule=TriggerRule.ALL_DONE)
    def consolidate(data_interval_end=None):
        """Consolidate every season, not just the one being fetched.

        Fetching is per season because the upstream APIs are shaped that way, but
        a show is one entity regardless of season, and the sources do not always
        agree which season it starts in - nine live titles were Summer 2026 to
        Kitsu and Spring 2026 to MAL. Merging per partition left every such pair
        as a visible duplicate, because the two halves were never in the same
        place at the same time.
        """
        from processing.consolidate import consolidate_catalogue

        _, _, run_date, _ = capture_for(data_interval_end)

        result = consolidate_catalogue(DATA_DIR, run_date)
        logger.info("Consolidated output: %s", result)

    @task(trigger_rule=TriggerRule.ALL_DONE)
    def refresh_catalog():
        from processing.duckdb_catalog import refresh_catalog as _refresh_catalog

        views = _refresh_catalog(DATA_DIR, DATA_DIR / "warehouse.duckdb")
        logger.info("Refreshed views: %s", views)

    # Both read anime_media_latest from the warehouse - independent of each other,
    # both tolerant of "no data yet" (see generate_digest/build_index docstrings).
    @task(trigger_rule=TriggerRule.ALL_DONE)
    def generate_digest(data_interval_end=None):
        from ai.digest.generate import generate_digest as _generate_digest

        _, _, run_date, _ = capture_for(data_interval_end)
        result = _generate_digest(DATA_DIR / "warehouse.duckdb", DATA_DIR / "digests", run_date)
        logger.info("Digest output: %s", result)

    @task(trigger_rule=TriggerRule.ALL_DONE)
    def build_search_index():
        from ai.search.build_index import build_index

        count = build_index(DATA_DIR / "warehouse.duckdb", DATA_DIR / "chroma")
        logger.info("Indexed %s titles", count)

    fetches = [fetch_anilist(), fetch_jikan(), fetch_mal(), fetch_kitsu()]
    catalog = fetches >> consolidate() >> refresh_catalog()
    catalog >> [generate_digest(), build_search_index()]


anime_seasonal_pipeline()

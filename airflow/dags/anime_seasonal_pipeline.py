from __future__ import annotations

import logging
from pathlib import Path

import pendulum
from airflow.decorators import dag, task
from airflow.utils.trigger_rule import TriggerRule

from ingestion.seasons import season_for_month
from ingestion.storage import write_parquet, write_raw_json

logger = logging.getLogger(__name__)

DATA_DIR = Path("/opt/airflow/data")


def _partition(season: str, season_year: int) -> str:
    return f"{season_year}-{season}"


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
    def fetch_anilist(logical_date=None):
        from ingestion.anilist.fetch_season import fetch_season
        from ingestion.anilist.transform import flatten_media

        season = season_for_month(logical_date.month)
        season_year = logical_date.year
        run_date = logical_date.to_date_string()
        partition = _partition(season, season_year)

        raw = fetch_season(season, season_year)
        logger.info("AniList: fetched %s titles", len(raw))
        write_raw_json(raw, DATA_DIR / "raw" / "anilist" / partition, run_date)
        write_parquet(
            [flatten_media(m) for m in raw],
            DATA_DIR / "processed" / "anilist_media" / partition,
            run_date,
        )

    @task
    def fetch_jikan(logical_date=None):
        from ingestion.jikan.fetch_season import fetch_season
        from ingestion.jikan.transform import flatten_media

        season = season_for_month(logical_date.month)
        season_year = logical_date.year
        run_date = logical_date.to_date_string()
        partition = _partition(season, season_year)

        raw = fetch_season(season, season_year)
        logger.info("Jikan: fetched %s titles", len(raw))
        write_raw_json(raw, DATA_DIR / "raw" / "jikan" / partition, run_date)
        write_parquet(
            [flatten_media(m) for m in raw],
            DATA_DIR / "processed" / "jikan_media" / partition,
            run_date,
        )

    @task
    def fetch_kitsu(logical_date=None):
        from ingestion.kitsu.fetch_season import fetch_season
        from ingestion.kitsu.transform import flatten_media

        season = season_for_month(logical_date.month)
        season_year = logical_date.year
        run_date = logical_date.to_date_string()
        partition = _partition(season, season_year)

        raw = fetch_season(season, season_year)
        logger.info("Kitsu: fetched %s titles", len(raw))
        write_raw_json(raw, DATA_DIR / "raw" / "kitsu" / partition, run_date)
        write_parquet(
            [flatten_media(m) for m in raw],
            DATA_DIR / "processed" / "kitsu_media" / partition,
            run_date,
        )

    # trigger_rule=ALL_DONE: run even if some (or all but one) of the fetch tasks
    # above failed - consolidate whatever snapshots actually landed rather than
    # blocking the whole pipeline on every source being healthy at once.
    @task(trigger_rule=TriggerRule.ALL_DONE)
    def consolidate(logical_date=None):
        from processing.consolidate import consolidate_partition

        season = season_for_month(logical_date.month)
        season_year = logical_date.year
        run_date = logical_date.to_date_string()
        partition = _partition(season, season_year)

        result = consolidate_partition(DATA_DIR, partition, run_date)
        logger.info("Consolidated output: %s", result)

    @task(trigger_rule=TriggerRule.ALL_DONE)
    def refresh_catalog():
        from processing.duckdb_catalog import refresh_catalog as _refresh_catalog

        views = _refresh_catalog(DATA_DIR, DATA_DIR / "warehouse.duckdb")
        logger.info("Refreshed views: %s", views)

    # Both read anime_media_latest from the warehouse - independent of each other,
    # both tolerant of "no data yet" (see generate_digest/build_index docstrings).
    @task(trigger_rule=TriggerRule.ALL_DONE)
    def generate_digest(logical_date=None):
        from ai.digest.generate import generate_digest as _generate_digest

        run_date = logical_date.to_date_string()
        result = _generate_digest(DATA_DIR / "warehouse.duckdb", DATA_DIR / "digests", run_date)
        logger.info("Digest output: %s", result)

    @task(trigger_rule=TriggerRule.ALL_DONE)
    def build_search_index():
        from ai.search.build_index import build_index

        count = build_index(DATA_DIR / "warehouse.duckdb", DATA_DIR / "chroma")
        logger.info("Indexed %s titles", count)

    fetches = [fetch_anilist(), fetch_jikan(), fetch_kitsu()]
    catalog = fetches >> consolidate() >> refresh_catalog()
    catalog >> [generate_digest(), build_search_index()]


anime_seasonal_pipeline()

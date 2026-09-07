from __future__ import annotations

import logging
from pathlib import Path

import pendulum
from airflow.decorators import dag, task

from ingestion.anilist.fetch_season import fetch_season, season_for_month

logger = logging.getLogger(__name__)

DATA_DIR = Path("/opt/airflow/data")


@dag(
    dag_id="anilist_seasonal_ingest",
    schedule="@weekly",
    start_date=pendulum.datetime(2026, 1, 1, tz="UTC"),
    catchup=False,
    tags=["ingestion", "anilist"],
)
def anilist_seasonal_ingest():
    @task
    def fetch_and_store(logical_date=None):
        from ingestion.anilist.storage import write_parquet_snapshot, write_raw_json

        run_date = logical_date.to_date_string()
        season = season_for_month(logical_date.month)
        season_year = logical_date.year
        partition = f"{season_year}-{season}"

        logger.info("Fetching AniList media for %s %s", season, season_year)
        media_list = fetch_season(season, season_year)
        logger.info("Fetched %s titles", len(media_list))

        raw_path = write_raw_json(media_list, DATA_DIR / "raw" / "anilist" / partition, run_date)
        parquet_path = write_parquet_snapshot(
            media_list, DATA_DIR / "processed" / "anilist_media" / partition, run_date
        )
        logger.info("Wrote %s and %s", raw_path, parquet_path)

    fetch_and_store()


anilist_seasonal_ingest()

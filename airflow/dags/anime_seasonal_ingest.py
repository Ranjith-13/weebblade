from __future__ import annotations

import logging
from pathlib import Path

import pendulum
from airflow.decorators import dag, task

from ingestion.seasons import season_for_month
from ingestion.storage import write_parquet, write_raw_json

logger = logging.getLogger(__name__)

DATA_DIR = Path("/opt/airflow/data")


def _partition(season: str, season_year: int) -> str:
    return f"{season_year}-{season}"


@dag(
    dag_id="anime_seasonal_ingest",
    schedule="@weekly",
    start_date=pendulum.datetime(2026, 1, 1, tz="UTC"),
    catchup=False,
    tags=["ingestion", "anime"],
)
def anime_seasonal_ingest():
    # One task per source, deliberately not chained together: if one API is down (as
    # AniList currently is) the others should still land data rather than the whole
    # DAG run blocking on it.

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

    fetch_anilist()
    fetch_jikan()
    fetch_kitsu()


anime_seasonal_ingest()

from __future__ import annotations

import logging
from pathlib import Path

import pendulum
from airflow.decorators import dag, task

logger = logging.getLogger(__name__)

# The same /data the weekly pipeline uses; see the note in anime_seasonal_pipeline.py.
DATA_DIR = Path("/data")


@dag(
    dag_id="anilist_airing",
    # Daily, apart from the weekly pipeline: the schedule is six requests, and a
    # countdown a week stale would miss every slipped broadcast. 06:00 UTC is
    # mid-afternoon in Tokyo, before the evening's broadcasts, and clear of the
    # weekly run's AniList requests at midnight Sunday, which share the same
    # 30-a-minute budget.
    schedule="0 6 * * *",
    start_date=pendulum.datetime(2026, 9, 14, tz="UTC"),
    catchup=False,
    tags=["ingestion", "anilist", "schedule"],
)
def anilist_airing():
    @task
    def fetch_airing(data_interval_end=None):
        """AniList's airing schedule for the coming weeks. See
        ingestion/anilist/fetch_airing.py.

        Writes one parquet file and touches nothing else: the warehouse view
        reads whichever file is newest when it is queried, so nothing here opens
        the warehouse, and nothing waits on the weekly pipeline."""
        from ingestion.anilist.fetch_airing import land_airing

        count = land_airing(
            DATA_DIR, data_interval_end.strftime("%Y-%m-%d"), int(data_interval_end.timestamp())
        )
        logger.info("Airing schedule: %s episodes", count)

    fetch_airing()


anilist_airing()

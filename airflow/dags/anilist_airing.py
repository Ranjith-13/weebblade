from __future__ import annotations

import logging
from pathlib import Path

import pendulum
from airflow.decorators import dag, task
from airflow.utils.trigger_rule import TriggerRule

logger = logging.getLogger(__name__)

# The same /data the weekly pipeline uses; see the note in anime_seasonal_pipeline.py.
DATA_DIR = Path("/data")


@dag(
    dag_id="anilist_airing",
    # Daily, apart from the weekly pipeline: the schedule is eleven requests and
    # the status check seven, and a countdown a week stale would miss every
    # slipped broadcast and every finale. 06:00 UTC is
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

    # After the schedule, not beside it: both spend AniList's 30 requests a
    # minute. ALL_DONE, because a failed schedule fetch is no reason to leave a
    # finished show counting down to its old slot.
    @task(trigger_rule=TriggerRule.ALL_DONE)
    def fetch_status(data_interval_end=None):
        """AniList's own status for the titles the catalogue calls airing. See
        ingestion/anilist/fetch_status.py.

        Reads the warehouse to know which titles to ask about - read-only, at
        06:00 UTC, well clear of the weekly run that writes it."""
        from ingestion.anilist.fetch_status import land_status

        count = land_status(DATA_DIR, data_interval_end.strftime("%Y-%m-%d"))
        logger.info("AniList status: %s titles answered", count)

    fetch_airing() >> fetch_status()


anilist_airing()

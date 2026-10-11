from __future__ import annotations

import logging
from pathlib import Path

import pendulum
from airflow.decorators import dag, task
from airflow.utils.trigger_rule import TriggerRule

from ingestion.seasons import capture_for

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
    # Jikan has been throughout, and AniList was until 2026-09) the others should
    # still land data rather than the whole DAG run blocking on it.
    #
    # The work itself is ingestion/land.py, which these four and the Airflow-free
    # entrypoint (pipeline/run.py) both call. It used to be written out here four
    # times, identically but for a module name - fine while this was the only way
    # to run the pipeline, and four copies free to drift the moment it was not.

    @task
    def fetch_anilist(data_interval_end=None):
        from ingestion.land import land_season

        land_season("anilist", data_interval_end, DATA_DIR)

    @task
    def fetch_jikan(data_interval_end=None):
        from ingestion.land import land_season

        land_season("jikan", data_interval_end, DATA_DIR)

    @task
    def fetch_mal(data_interval_end=None):
        """The OFFICIAL MyAnimeList API v2, not the Jikan mirror.

        Jikan has returned 504 ("MyAnimeList may be down") for this project's
        whole life, but MAL itself answers 200 and api.myanimelist.net returns a
        well-formed "Invalid client id" - verified, not assumed. MAL was never
        the broken part; Jikan was. This source exists because MAL carries the
        two columns that are null for 100% of stored rows, studios and
        source_material, plus scores for titles Kitsu does not rate.

        Skips cleanly when MAL_CLIENT_ID is unset - see ingestion/land.py - so
        the DAG stays green on an installation that has not registered one,
        rather than failing a task for a configuration choice.
        """
        from ingestion.land import land_season

        land_season("mal", data_interval_end, DATA_DIR)

    @task
    def fetch_kitsu(data_interval_end=None):
        from ingestion.land import land_season

        land_season("kitsu", data_interval_end, DATA_DIR)

    @task(trigger_rule=TriggerRule.ALL_DONE)
    def fetch_bridge_ids(data_interval_end=None):
        """The MAL id AniList holds for a title only Kitsu lists. See
        ingestion/anilist/bridge_ids.py.

        After the fetches rather than beside them: this and fetch_anilist share
        AniList's 30 requests a minute. It writes its own record and nothing
        else, and is budgeted, so a week that finds a hundred new such titles
        searches sixty of them and leaves the rest for the next run."""
        from ingestion.anilist.bridge_ids import land_bridge

        _, _, run_date, _ = capture_for(data_interval_end)
        logger.info("MAL ids by AniList: %s found", land_bridge(DATA_DIR, run_date))

    @task(trigger_rule=TriggerRule.ALL_DONE)
    def build_bridge():
        """Which of those ids may actually be used, by the one rule that the
        measurement supports: the two rows premiered on the same day. See
        processing/bridge.py.

        After the fetches, because it compares this week's snapshots, and before
        consolidate, which reads what it writes."""
        from processing.bridge import build_bridge as _build

        logger.info("MAL ids adopted: %s", _build(DATA_DIR))

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
    def record_changes(data_interval_end=None):
        """What each source now says differently about a title from its last
        fetch. See processing/changes.py.

        After consolidating, so the registry already holds any title first seen
        this run and its changes land on it; before the refresh, so the first
        run's file is there when the view is made. It reads only the sources'
        snapshots and the registry, and writes one file - never the warehouse."""
        from processing.changes import record_changes as _record_changes

        _, _, run_date, _ = capture_for(data_interval_end)
        logger.info("Changes: %s", _record_changes(DATA_DIR, run_date))

    @task(trigger_rule=TriggerRule.ALL_DONE)
    def refresh_catalog():
        from processing.duckdb_catalog import refresh_catalog as _refresh_catalog

        views = _refresh_catalog(DATA_DIR, DATA_DIR / "warehouse.duckdb")
        logger.info("Refreshed views: %s", views)

    # Both read anime_media_latest from the warehouse, and build_search_index
    # writes its vectors back into it, so they stay in the single-writer line
    # with everything else that opens the file (see the chain at the bottom).
    # Both tolerate "no data yet" - see generate_digest/build_index.
    @task(trigger_rule=TriggerRule.ALL_DONE)
    def generate_digest(data_interval_end=None):
        from ai.digest.generate import generate_digest as _generate_digest

        _, _, run_date, _ = capture_for(data_interval_end)
        result = _generate_digest(DATA_DIR / "warehouse.duckdb", DATA_DIR / "digests", run_date)
        logger.info("Digest output: %s", result)

    @task(trigger_rule=TriggerRule.ALL_DONE)
    def build_search_index():
        from ai.search.build_index import build_index

        count = build_index(DATA_DIR / "warehouse.duckdb")
        logger.info("Indexed %s titles", count)

    @task(trigger_rule=TriggerRule.ALL_DONE)
    def fetch_mal_relations(data_interval_end=None):
        """MAL's related titles, for the franchise graph. See
        ingestion/mal/fetch_relations.py.

        After the catalogue refresh because the plan reads this week's titles:
        the new ones have never been fetched, the airing ones may have gained a
        sequel, and anything they name that has never been fetched extends the
        franchise past the catalogue. A few hundred requests a week once the
        first full fetch is done; the budget stops a week that finds a huge
        franchise from running for hours, and the rest waits for next week.
        Skips cleanly without MAL_CLIENT_ID, like fetch_mal."""
        from ingestion.mal.client import MissingClientId
        from ingestion.mal.fetch_relations import fetch_until_complete

        _, _, run_date, _ = capture_for(data_interval_end)
        try:
            result = fetch_until_complete(DATA_DIR, run_date, budget=2000)
        except MissingClientId as exc:
            logger.warning("Skipping MAL relations: %s", exc)
            return
        logger.info("Related titles: %s fetched, %s edges, %s failed", result.titles, result.edges, len(result.failed))

    @task(trigger_rule=TriggerRule.ALL_DONE)
    def build_franchises():
        """Rebuild the franchise table from every stored relation, then refresh
        the warehouse views so the first build is queryable at once."""
        from processing.duckdb_catalog import refresh_catalog as _refresh_catalog
        from processing.franchise import build_franchises as _build

        logger.info("Franchises: %s", _build(DATA_DIR))
        _refresh_catalog(DATA_DIR, DATA_DIR / "warehouse.duckdb")

    @task(trigger_rule=TriggerRule.ALL_DONE)
    def check_run(data_interval_end=None, dag_run=None):
        """Read what the run produced, write its numbers down, and fail the run
        if something is wrong. See processing/run_checks.py.

        Last, and ALL_DONE like everything after the fetches: every other task
        runs whatever happened upstream, so without this a task in the middle
        can fail under a run that still ends green."""
        from airflow.exceptions import AirflowFailException

        from processing.run_checks import check_weekly, notify

        _, _, run_date, _ = capture_for(data_interval_end)
        failed = [ti.task_id for ti in dag_run.get_task_instances()
                  if ti.task_id != "check_run" and ti.state in ("failed", "upstream_failed")]
        record = check_weekly(DATA_DIR, run_date, failed)
        logger.info("Run checks:\n%s", record.summary())
        if not record.passed:
            notify(record)
            raise AirflowFailException(record.summary())

    fetches = [fetch_anilist(), fetch_jikan(), fetch_mal(), fetch_kitsu()]
    # In a line, not in parallel: each of these opens the warehouse file, and
    # DuckDB allows one writer. The digest and the index read it after.
    catalog = (fetches >> fetch_bridge_ids() >> build_bridge() >> consolidate()
               >> record_changes() >> refresh_catalog()
               >> fetch_mal_relations() >> build_franchises())
    catalog >> generate_digest() >> build_search_index() >> check_run()


anime_seasonal_pipeline()

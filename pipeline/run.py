"""Run a pipeline without Airflow.

The DAGs in airflow/dags are still the orchestration this project is built
around, and they still run it on the server. This is the same work, in the same
order, started by a command - which is what a GitHub Actions runner, a cron
entry, or a person debugging on a laptop can actually use.

It calls exactly the functions the DAG tasks call. Nothing here reimplements a
step; where a step needed code that only existed inside a task body, that code
moved somewhere both can reach it (ingestion/land.py). Two entrypoints over one
implementation drift far less than two implementations.

WHAT IT MIRRORS, AND WHAT IT DOES NOT

Every task downstream of the fetches carries trigger_rule=ALL_DONE: a failure
does not stop the run, because consolidating whatever landed beats blocking the
whole pipeline on one sick API. So a failing step here is recorded and the run
continues, exactly as it would there.

What decides the outcome is the same check the DAG ends with
(processing/run_checks.py): it reads what the run produced, compares it with the
run before, and fails on a source that landed nothing, a title lost or split, a
burst of merges, or a warehouse still serving last week. The failed step names
go into it, so a step that died is judged alongside the numbers rather than
instead of them. A failing check exits non-zero, which is how a scheduler -
Airflow or Actions - learns the run was bad.

What it does not mirror: parallelism. The DAG fetches four sources at once; this
does them in order. On a weekly run over four small APIs that costs a couple of
minutes and buys a log you can read top to bottom.

    python -m pipeline.run weekly
    python -m pipeline.run daily --data-dir ./data --at 2026-10-11T06:00:00+00:00
    python -m pipeline.run weekly --dry-run
"""

from __future__ import annotations

import argparse
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)

DATA_DIR = Path("/data")


@dataclass(frozen=True)
class Step:
    """One task's worth of work, named as the DAG names it so a failure reads
    the same in both places - and so run_checks, which is given these names,
    reports something a person can find."""

    name: str
    run: Callable[[Path, Any, str], None]


# --- the steps, one per DAG task ------------------------------------------------------
#
# Each takes (data_dir, at, run_date) whether it needs all three or not: a
# uniform signature is what lets the runner below stay a loop, and what lets a
# test replace any one of them.


def _fetch(source: str) -> Callable[[Path, Any, str], None]:
    def step(data_dir: Path, at: Any, run_date: str) -> None:
        from ingestion.land import land_season

        land_season(source, at, data_dir)

    return step


def _fetch_bridge_ids(data_dir: Path, at: Any, run_date: str) -> None:
    from ingestion.anilist.bridge_ids import land_bridge

    logger.info("MAL ids by AniList: %s found", land_bridge(data_dir, run_date))


def _build_bridge(data_dir: Path, at: Any, run_date: str) -> None:
    from processing.bridge import build_bridge

    logger.info("MAL ids adopted: %s", build_bridge(data_dir))


def _consolidate(data_dir: Path, at: Any, run_date: str) -> None:
    from processing.consolidate import consolidate_catalogue

    logger.info("Consolidated output: %s", consolidate_catalogue(data_dir, run_date))


def _record_changes(data_dir: Path, at: Any, run_date: str) -> None:
    from processing.changes import record_changes

    logger.info("Changes: %s", record_changes(data_dir, run_date))


def _refresh_catalog(data_dir: Path, at: Any, run_date: str) -> None:
    from processing.duckdb_catalog import refresh_catalog

    logger.info("Refreshed views: %s", refresh_catalog(data_dir, data_dir / "warehouse.duckdb"))


def _fetch_mal_relations(data_dir: Path, at: Any, run_date: str) -> None:
    from ingestion.mal.client import MissingClientId
    from ingestion.mal.fetch_relations import fetch_until_complete

    try:
        result = fetch_until_complete(data_dir, run_date, budget=2000)
    except MissingClientId as exc:
        logger.warning("Skipping MAL relations: %s", exc)
        return
    logger.info(
        "Related titles: %s fetched, %s edges, %s failed",
        result.titles, result.edges, len(result.failed),
    )


def _build_franchises(data_dir: Path, at: Any, run_date: str) -> None:
    from processing.duckdb_catalog import refresh_catalog
    from processing.franchise import build_franchises

    logger.info("Franchises: %s", build_franchises(data_dir))
    refresh_catalog(data_dir, data_dir / "warehouse.duckdb")


def _generate_digest(data_dir: Path, at: Any, run_date: str) -> None:
    from ai.digest.generate import generate_digest

    logger.info(
        "Digest output: %s",
        generate_digest(data_dir / "warehouse.duckdb", data_dir / "digests", run_date),
    )


def _build_search_index(data_dir: Path, at: Any, run_date: str) -> None:
    from ai.search.build_index import build_index

    logger.info("Indexed %s titles", build_index(data_dir / "warehouse.duckdb"))


def _build_similar(data_dir: Path, at: Any, run_date: str) -> None:
    """Neighbours for "More like this". A step of its own, not part of the index
    build, for the two reasons they are separate things: it embeds a different
    document (ai/search/similar explains why the search one cannot be reused),
    and either can fail without taking the other's table down."""
    from ai.search.similar import build_similar

    logger.info("Related %s titles", build_similar(data_dir / "warehouse.duckdb"))


def _fetch_airing(data_dir: Path, at: Any, run_date: str) -> None:
    from ingestion.anilist.fetch_airing import land_airing

    logger.info("Airing schedule: %s episodes", land_airing(data_dir, run_date, int(at.timestamp())))


def _resolve_ids(data_dir: Path, at: Any, run_date: str) -> None:
    from ingestion.anilist.resolve_ids import land_resolved

    logger.info("AniList ids: %s titles gained one", land_resolved(data_dir, run_date))


def _fetch_status(data_dir: Path, at: Any, run_date: str) -> None:
    from ingestion.anilist.fetch_status import land_status

    logger.info("AniList status: %s titles answered", land_status(data_dir, run_date))


WEEKLY = [
    Step("fetch_anilist", _fetch("anilist")),
    Step("fetch_mal", _fetch("mal")),
    Step("fetch_kitsu", _fetch("kitsu")),
    Step("fetch_bridge_ids", _fetch_bridge_ids),
    Step("build_bridge", _build_bridge),
    Step("consolidate", _consolidate),
    Step("record_changes", _record_changes),
    Step("refresh_catalog", _refresh_catalog),
    Step("fetch_mal_relations", _fetch_mal_relations),
    Step("build_franchises", _build_franchises),
    Step("generate_digest", _generate_digest),
    Step("build_search_index", _build_search_index),
    # After build_franchises, and that ordering is load-bearing: the neighbours
    # exclude a title's own franchise while they are computed, because a title
    # page already lists its franchise in full above this block.
    Step("build_similar", _build_similar),
]

DAILY = [
    Step("fetch_airing", _fetch_airing),
    Step("resolve_ids", _resolve_ids),
    Step("fetch_status", _fetch_status),
    # LAST, AND IT HAS TO BE. The weekly list has carried a refresh since it was
    # written; the daily one did not, because its fetches only ever replaced the
    # CONTENTS of files the views already described. That held until a fetch
    # changed a file's SHAPE.
    #
    # DuckDB binds a view's column list when the view is created, and these
    # views are `SELECT l.*` over a parquet file. _ensure_warehouse builds them
    # before the steps run, from the lake as it was restored; fetch_status then
    # wrote processed/current/anilist_status.parquet with two more columns, and
    # the check that reads the warehouse next died on "Contents of view were
    # altered: types don't match". The fetch had worked perfectly - 281 titles
    # answered, scores and all - and the run still went red at the end.
    #
    # Rebuilding the views after the fetches is both the fix and the honest
    # description of the daily run: it changes the lake, so what reads the lake
    # should be re-derived before anything queries it. A second of work, and it
    # removes the whole class rather than the one column that found it.
    Step("refresh_catalog", _refresh_catalog),
]


def _ensure_warehouse(data_dir: Path) -> None:
    """Make sure there is a warehouse here before any step reads one.

    Not a step, because it is not work the pipeline does - it is a fact about
    where the pipeline is running. The server keeps a warehouse between runs, so
    the daily DAG can assume one; a GitHub runner starts empty and the daily
    steps (resolve_ids, fetch_status, the check) all read it.

    Rebuilding is right rather than restoring it from somewhere: refresh_catalog
    bakes each parquet file's ABSOLUTE path into every view, so a warehouse built
    on another machine resolves to nothing here - and does it by returning no
    rows rather than erroring, which is the worst way to fail. A second's work
    gets views that point at this machine.
    """
    warehouse = data_dir / "warehouse.duckdb"
    if warehouse.exists():
        return
    from processing.duckdb_catalog import refresh_catalog

    logger.info("No warehouse here yet - building views over the lake first")
    refresh_catalog(data_dir, warehouse)


def run(which: str, data_dir: Path = DATA_DIR, at: datetime | None = None) -> int:
    """Run a pipeline and return a process exit code: 0 passed, 1 did not."""
    from ingestion.seasons import capture_for
    from processing.run_checks import check_daily, check_weekly, notify

    at = at or datetime.now(timezone.utc)
    _, _, run_date, _ = capture_for(at)
    steps = WEEKLY if which == "weekly" else DAILY
    logger.info("%s run for %s (%s steps)", which, run_date, len(steps))
    _ensure_warehouse(data_dir)

    failed: list[str] = []
    for step in steps:
        logger.info("--- %s", step.name)
        try:
            step.run(data_dir, at, run_date)
        except Exception:
            # Deliberately not re-raised: every task after the fetches is
            # ALL_DONE in the DAG, and a run that limps to its own check and
            # reports what happened is worth more than one that stops at the
            # first sick API.
            logger.exception("%s failed", step.name)
            failed.append(step.name)

    check = check_weekly if which == "weekly" else check_daily
    record = check(data_dir, run_date, failed)
    logger.info("Run checks:\n%s", record.summary())
    if not record.passed:
        notify(record)
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("which", choices=("weekly", "daily"))
    parser.add_argument("--data-dir", type=Path, default=DATA_DIR)
    parser.add_argument(
        "--at",
        type=datetime.fromisoformat,
        help="End of the interval being captured, ISO 8601. Defaults to now, UTC. "
             "This is Airflow's data_interval_end, never its logical_date.",
    )
    parser.add_argument("--dry-run", action="store_true", help="List the steps and stop.")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if args.dry_run:
        for i, step in enumerate(WEEKLY if args.which == "weekly" else DAILY, 1):
            print(f"{i:2}. {step.name}")
        return 0
    return run(args.which, args.data_dir, args.at)


if __name__ == "__main__":
    raise SystemExit(main())

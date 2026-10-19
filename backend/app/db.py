from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Iterator

import duckdb
from fastapi import HTTPException

logger = logging.getLogger(__name__)

DATA_DIR = Path(os.environ.get("DATA_DIR", "/data"))
DB_PATH = DATA_DIR / "warehouse.duckdb"

# WHAT DUCKDB IS ALLOWED TO TAKE, because by default it is "most of the machine"
# and this machine is 512 MB that something else is already using.
#
# DuckDB sizes its buffer pool at ~80% of the memory it can SEE, and a container
# sees the host's /proc/meminfo rather than its own cgroup limit - on the box
# this was measured it read 11.9 GiB. Threads default to the host's core count
# (12 there) on a container billed at 0.1 CPU, and each one carries buffers.
# So the pool was sized from a number with nothing to do with what Render will
# actually allow before killing the process.
#
# Measured against the live 11,992-title warehouse, peak RSS over one reader's
# path - catalogue, a season, a search, then /scores:
#
#   /health             87 MB
#   /catalogue         238 MB   (+151, the buffer pool)
#   /search, first     391 MB   (+153, the ONNX embedder)
#   /scores/settling   505 MB   (+114, 66k dated rows and window functions)
#
# against a 512 MB limit. Seven megabytes, and the input to the last one grows
# every week. Bounded to the values below the same path peaks at 402 MB.
#
# NOT AS LOW AS IT WILL GO, because a limit is not a promise of spilling. On
# DuckDB 1.5.6 a query that cannot fit raises OutOfMemoryException rather than
# going to disk: /scores/settling completes at 64 MB and fails at 16. On the
# 1.1.3 this service pins, a sort that raises on 1.5.6 ran to completion
# instead - so the two do not agree, and only one of them is what production
# runs. The limit is therefore set at about three times what the heaviest query
# needs today, so growth has somewhere to go on either - and run_query turns the
# exception into a 503 should it arrive, because one endpoint degrading is a far
# better outcome than the container being killed with no error anyone can trace
# back to a query.
#
# Environment-settable so it can be tuned on a running service without a deploy.
MEMORY_LIMIT = os.environ.get("DUCKDB_MEMORY_LIMIT", "192MB")
THREADS = os.environ.get("DUCKDB_THREADS", "2")


def _connect() -> duckdb.DuckDBPyConnection:
    """A read-only connection that cannot outgrow the container.

    Set per connection, because that is the only scope DuckDB has for these:
    every request opens its own, so an unbounded one anywhere is an unbounded
    one everywhere.
    """
    con = duckdb.connect(str(DB_PATH), read_only=True)
    con.execute(f"SET memory_limit='{MEMORY_LIMIT}'")
    con.execute(f"SET threads={THREADS}")
    return con


def get_db() -> Iterator[duckdb.DuckDBPyConnection]:
    """FastAPI dependency: a read-only connection to the warehouse.

    Raises a clear 503 (not a 500) if the pipeline hasn't produced a warehouse file
    yet - a normal early-project state (or a run where every ingestion source
    failed), not a bug.
    """
    if not DB_PATH.exists():
        raise HTTPException(503, "Warehouse not built yet - the pipeline hasn't run successfully")
    con = _connect()
    try:
        yield con
    finally:
        con.close()


def get_db_optional() -> Iterator[duckdb.DuckDBPyConnection | None]:
    """Like get_db, but yields None where get_db would refuse with a 503.

    For an endpoint that must validate its own input first. A dependency that
    raises does so during dependency resolution, which happens before FastAPI
    checks the query parameters - so a 503 about the warehouse would pre-empt
    the 422 a malformed query has earned. /search is the case: its query is user
    text, and "your query was empty" is the more useful answer even on a
    warehouse that does not exist. The endpoint raises the 503 itself once it
    knows the request was well formed.
    """
    if not DB_PATH.exists():
        yield None
        return
    con = _connect()
    try:
        yield con
    finally:
        con.close()


def run_query(
    con: duckdb.DuckDBPyConnection, sql: str, params: list[Any] | None = None
) -> list[dict[str, Any]]:
    """Run a query and return rows as plain dicts.

    Converts a missing view/table into a 503 rather than a 500 - happens whenever
    every ingestion source has failed on a given run (see PROGRESS.md), which the
    warehouse file existing doesn't rule out on its own.
    """
    try:
        return con.execute(sql, params or []).fetch_arrow_table().to_pylist()
    except duckdb.CatalogException as exc:
        raise HTTPException(
            503, "No data available yet - the pipeline hasn't produced results"
        ) from exc
    except duckdb.OutOfMemoryException as exc:
        # A 503, not the 500 this would otherwise be. The limit above is what
        # stops the container being killed outright, and this is what makes
        # hitting it survivable: 503 is the status the frontend already treats
        # as "this block has nothing to say" rather than as a broken page (see
        # getScoreSettling in frontend/lib/api.ts), so the one heavy endpoint
        # goes quiet and the site stays up. If this starts appearing in logs the
        # query needs narrowing, or DUCKDB_MEMORY_LIMIT needs raising - and the
        # log line is the only warning that will come.
        logger.warning("Query exceeded DUCKDB_MEMORY_LIMIT=%s: %s", MEMORY_LIMIT, sql[:120])
        raise HTTPException(
            503, "That query needs more memory than this service has - try a narrower one"
        ) from exc

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Iterator

import duckdb
from fastapi import HTTPException

DATA_DIR = Path(os.environ.get("DATA_DIR", "/data"))
DB_PATH = DATA_DIR / "warehouse.duckdb"


def get_db() -> Iterator[duckdb.DuckDBPyConnection]:
    """FastAPI dependency: a read-only connection to the warehouse.

    Raises a clear 503 (not a 500) if the pipeline hasn't produced a warehouse file
    yet - a normal early-project state (or a run where every ingestion source
    failed), not a bug.
    """
    if not DB_PATH.exists():
        raise HTTPException(503, "Warehouse not built yet - the pipeline hasn't run successfully")
    con = duckdb.connect(str(DB_PATH), read_only=True)
    try:
        yield con
    finally:
        con.close()


def get_db_optional() -> Iterator[duckdb.DuckDBPyConnection | None]:
    """Like get_db, but yields None where get_db would refuse with a 503.

    For endpoints whose answer does not come from the warehouse and is only
    decorated from it: /search's matches come from the vector index, so a missing
    warehouse should cost the results their artwork, not the results themselves.
    It also never raises during dependency resolution, where a 503 would pre-empt
    the 422 a malformed query deserves.
    """
    if not DB_PATH.exists():
        yield None
        return
    con = duckdb.connect(str(DB_PATH), read_only=True)
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

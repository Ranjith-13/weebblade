from __future__ import annotations

import json
import logging

import duckdb
from fastapi import APIRouter, Depends, Query

from ..db import get_db_optional
from ..schemas import RunCheck

router = APIRouter(prefix="/runs", tags=["runs"])
logger = logging.getLogger(__name__)


@router.get("", response_model=list[RunCheck])
def runs(
    dag: str | None = Query(None, description="anime_seasonal_pipeline or anilist_airing"),
    limit: int = Query(10, ge=1, le=100),
    con: duckdb.DuckDBPyConnection | None = Depends(get_db_optional),
) -> list[RunCheck]:
    """What recent pipeline runs checked about their own output, newest first:
    their numbers, and what failed them if anything did. Written by each DAG's
    last task; see processing/run_checks.py.

    From the warehouse's `run_check` table rather than from
    DATA_DIR/processed/runs, for the reason the digest router explains: the API
    no longer shares a disk with the pipeline that writes these. The record is
    stored as the JSON it was written as and parsed here, so a check that learns
    a new field needs no change to the warehouse.
    """
    sql = "SELECT dag, record FROM run_check"
    params: list = []
    if dag:
        sql += " WHERE dag = ?"
        params.append(dag)
    # By date first, then DAG - two DAGs run on the same day and the newest is
    # the question being asked. LIMIT in SQL, so a long history costs nothing.
    sql += " ORDER BY run_date DESC, dag DESC LIMIT ?"
    params.append(limit)

    if con is None:
        return []
    try:
        rows = con.execute(sql, params).fetch_arrow_table().to_pylist()
    except (duckdb.CatalogException, duckdb.IOException):
        # No run_check in this warehouse, or a view over records that are no
        # longer on disk. An empty list, not a 503 - nothing is broken.
        return []

    out: list[RunCheck] = []
    for row in rows:
        try:
            out.append(RunCheck(**json.loads(row["record"])))
        except (TypeError, ValueError):
            # One unreadable record costs its own entry, not the list.
            logger.warning("Could not read the run record for %s", row["dag"], exc_info=True)
    return out

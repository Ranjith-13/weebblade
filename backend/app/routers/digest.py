from __future__ import annotations

import duckdb
from fastapi import APIRouter, Depends, HTTPException

from ..db import get_db, get_db_optional
from ..schemas import DigestResponse

router = APIRouter(prefix="/digest", tags=["digest"])

# FROM THE WAREHOUSE, NOT FROM A DIRECTORY
#
# These used to read DATA_DIR/digests/*.md, which was right while the API and
# the pipeline shared a disk. They do not: the API now serves one published file
# it downloads at startup (backend/app/warehouse.py) and has no lake behind it,
# so a digest on the pipeline's filesystem would simply never be seen. The
# digest is four pages of the site - the home page, the index, each dated page,
# and the sitemap's entries - so all four would have gone live empty.
#
# processing/duckdb_catalog._prose_views puts them in the warehouse as a
# `digest` table, and materialising carries it into the published artifact.
_SELECT = "SELECT run_date, content FROM digest"


def _digests(
    con: duckdb.DuckDBPyConnection | None, sql: str, params: list | None = None
) -> list[dict] | None:
    """Rows, or None where this warehouse has no digests to read at all.

    None rather than an empty list, because the two have different answers: no
    digest table is "the pipeline has not written one yet", which each endpoint
    below reports in its own terms.
    """
    if con is None:
        return None
    try:
        return con.execute(sql, params or []).fetch_arrow_table().to_pylist()
    except (duckdb.CatalogException, duckdb.IOException):
        # CatalogException: no digest view in this warehouse. IOException: a
        # view over files that are no longer there, which only an unmaterialised
        # warehouse can have. Neither is a fault worth a 500.
        return None


@router.get("", response_model=list[str])
def list_digests(
    con: duckdb.DuckDBPyConnection | None = Depends(get_db_optional),
) -> list[str]:
    """Every digest there is, newest first.

    Optional connection, so this answers [] rather than 503 on a warehouse that
    has none - an empty index is an honest answer to "what digests exist", and
    the site's sitemap asks this on every build.
    """
    rows = _digests(con, f"{_SELECT} ORDER BY run_date DESC")
    return [row["run_date"] for row in rows or []]


@router.get("/latest", response_model=DigestResponse)
def latest_digest(con: duckdb.DuckDBPyConnection = Depends(get_db)) -> DigestResponse:
    # Registered before /{run_date} so "latest" isn't swallowed by that path param.
    rows = _digests(con, f"{_SELECT} ORDER BY run_date DESC LIMIT 1")
    if not rows:
        raise HTTPException(503, "No digest generated yet")
    return DigestResponse(**rows[0])


@router.get("/{run_date}", response_model=DigestResponse)
def get_digest(
    run_date: str, con: duckdb.DuckDBPyConnection = Depends(get_db)
) -> DigestResponse:
    rows = _digests(con, f"{_SELECT} WHERE run_date = ?", [run_date])
    if not rows:
        raise HTTPException(404, f"No digest found for {run_date}")
    return DigestResponse(**rows[0])

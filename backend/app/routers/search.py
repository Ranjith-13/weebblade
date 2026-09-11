from __future__ import annotations

import os
from pathlib import Path

import duckdb
from fastapi import APIRouter, Depends, HTTPException, Query, Request

from ..db import get_db_optional
from ..limiter import limiter
from ..schemas import SearchResponse, SearchResult

router = APIRouter(prefix="/search", tags=["search"])

DATA_DIR = Path(os.environ.get("DATA_DIR", "/data"))
CHROMA_DIR = DATA_DIR / "chroma"

_DECORATION = ("wb_id", "poster_url", "score_100", "format", "status")


def _rows(con: duckdb.DuckDBPyConnection, sql: str, params: list) -> list[dict]:
    try:
        return con.execute(sql, params).fetch_arrow_table().to_pylist()
    except (duckdb.CatalogException, duckdb.BinderException):
        return []


def _decorate(con: duckdb.DuckDBPyConnection | None, results: list[SearchResult]) -> list[SearchResult]:
    """Give each match its poster, score and format from the warehouse.

    Without this a client could only draw a result as text, or hold the whole
    catalogue to look each one up - which the frontend did, shipping all 2,755
    titles in the page to decorate twenty.

    The index is keyed by whichever source won a title's merge when it was built.
    If a later merge changed the winner, that key is no longer a row in
    anime_media_latest, so a miss falls through the identity registry, which knows
    every key a title was ever made of - the same path /anime/{source}/{source_id}
    takes. A title found by neither comes back as it was, never dropped.
    """
    if con is None or not results:
        return results

    keys = [f"{r.source}:{r.source_id}" for r in results]
    marks = ", ".join("?" * len(keys))
    found = {
        f"{row['source']}:{row['source_id']}": row
        for row in _rows(
            con, f"SELECT * FROM anime_media_latest WHERE source || ':' || source_id IN ({marks})", keys
        )
    }
    missing = [k for k in keys if k not in found]
    if missing:
        marks = ", ".join("?" * len(missing))
        for row in _rows(
            con,
            "SELECT i.source_key AS matched_key, m.* FROM anime_identity i "
            f"JOIN anime_media_latest m ON m.wb_id = i.wb_id WHERE i.source_key IN ({marks})",
            missing,
        ):
            found[row["matched_key"]] = row

    return [
        r.model_copy(update={f: found[k].get(f) for f in _DECORATION}) if k in found else r
        for r, k in zip(results, keys)
    ]


@router.get("", response_model=SearchResponse)
@limiter.limit("20/minute")
def search(
    request: Request,
    q: str = Query(..., min_length=1),
    n: int = Query(10, ge=1, le=50),
    con: duckdb.DuckDBPyConnection | None = Depends(get_db_optional),
) -> SearchResponse:
    if not CHROMA_DIR.exists():
        raise HTTPException(503, "Search index not built yet")

    from ai.search.query import find_similar

    try:
        matches = find_similar(CHROMA_DIR, q, n_results=n)
    except Exception as exc:
        # chromadb's own exception types for a missing/empty collection vary by
        # version - treat any indexing-layer failure here as "not ready" rather
        # than leaking a 500 for what's an expected early-project state.
        raise HTTPException(503, "Search index not ready") from exc

    results = [SearchResult(**m) for m in matches]
    return SearchResponse(query=q, results=_decorate(con, results))

from __future__ import annotations

import duckdb
from fastapi import APIRouter, Depends, HTTPException, Query, Request

from ..db import get_db_optional
from ..limiter import limiter
from ..schemas import SearchResponse, SearchResult

router = APIRouter(prefix="/search", tags=["search"])


@router.get("", response_model=SearchResponse)
@limiter.limit("20/minute")
def search(
    request: Request,
    q: str = Query(..., min_length=1),
    n: int = Query(10, ge=1, le=50),
    con: duckdb.DuckDBPyConnection | None = Depends(get_db_optional),
) -> SearchResponse:
    """Semantic search over the catalogue. See ai/search/query.py.

    One query against the warehouse: the vectors are a table beside the titles,
    so matches arrive with their artwork, score, format and status already on
    them. Before, they came from a Chroma collection in its own directory and had
    to be decorated afterwards - which also meant a match whose key had since
    lost a merge came back as bare text.
    """
    from ai.search.query import find_similar

    # Not a raising dependency: that would resolve before the query parameter is
    # validated, and answer a malformed query with the wrong complaint. See
    # db.get_db_optional.
    if con is None:
        raise HTTPException(503, "Warehouse not built yet - the pipeline hasn't run successfully")

    try:
        matches = find_similar(con, q, n_results=n)
    except duckdb.CatalogException as exc:
        # No anime_embedding table yet: the pipeline has not built an index on
        # this warehouse. An expected early state, not a bug - a 503 says come
        # back, where a 500 would say something is broken.
        raise HTTPException(503, "Search index not built yet") from exc

    return SearchResponse(query=q, results=[SearchResult(**m) for m in matches])

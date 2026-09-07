from __future__ import annotations

import os
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query

from ..schemas import SearchResponse, SearchResult

router = APIRouter(prefix="/search", tags=["search"])

DATA_DIR = Path(os.environ.get("DATA_DIR", "/data"))
CHROMA_DIR = DATA_DIR / "chroma"


@router.get("", response_model=SearchResponse)
def search(q: str = Query(..., min_length=1), n: int = Query(10, ge=1, le=50)) -> SearchResponse:
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

    return SearchResponse(query=q, results=[SearchResult(**m) for m in matches])

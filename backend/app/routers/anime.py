from __future__ import annotations

import duckdb
from fastapi import APIRouter, Depends, HTTPException, Query

from ..db import get_db, run_query
from ..schemas import Anime, AnimeListResponse

router = APIRouter(prefix="/anime", tags=["anime"])

_SORT_COLUMNS = {
    "score_desc": "score_100 DESC NULLS LAST",
    "popularity_desc": "popularity DESC NULLS LAST",
    "title": "COALESCE(title_english, title_romaji) ASC",
}


def _build_filters(
    season: str | None,
    season_year: int | None,
    genre: str | None,
    format: str | None,
    min_score: float | None,
) -> tuple[str, list]:
    clauses = []
    params: list = []

    if season:
        clauses.append("season = ?")
        params.append(season.upper())
    if season_year is not None:
        clauses.append("season_year = ?")
        params.append(season_year)
    if genre:
        # case-insensitive: the underlying data mixes casing across sources
        # (Kitsu's format/genre-like fields in particular aren't consistently
        # Title Case), and an exact-match filter would just produce confusing
        # empty results for a caller who guessed the wrong case.
        clauses.append("EXISTS (SELECT 1 FROM UNNEST(genres) AS t(g) WHERE LOWER(g) = LOWER(?))")
        params.append(genre)
    if format:
        clauses.append("LOWER(format) = LOWER(?)")
        params.append(format)
    if min_score is not None:
        clauses.append("score_100 >= ?")
        params.append(min_score)

    where_sql = " AND ".join(clauses) if clauses else "TRUE"
    return where_sql, params


@router.get("", response_model=AnimeListResponse)
def list_anime(
    season: str | None = None,
    season_year: int | None = None,
    genre: str | None = None,
    format: str | None = None,
    min_score: float | None = None,
    sort: str = Query("score_desc", pattern="^(score_desc|popularity_desc|title)$"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    con: duckdb.DuckDBPyConnection = Depends(get_db),
) -> AnimeListResponse:
    where_sql, params = _build_filters(season, season_year, genre, format, min_score)
    order_sql = _SORT_COLUMNS[sort]

    total = run_query(
        con, f"SELECT COUNT(*) AS n FROM anime_media_latest WHERE {where_sql}", params
    )[0]["n"]
    rows = run_query(
        con,
        f"SELECT * FROM anime_media_latest WHERE {where_sql} "
        f"ORDER BY {order_sql} LIMIT ? OFFSET ?",
        params + [limit, offset],
    )

    return AnimeListResponse(total=total, limit=limit, offset=offset, items=rows)


@router.get("/{source}/{source_id}", response_model=Anime)
def get_anime(
    source: str, source_id: str, con: duckdb.DuckDBPyConnection = Depends(get_db)
) -> Anime:
    rows = run_query(
        con,
        "SELECT * FROM anime_media_latest WHERE source = ? AND source_id = ?",
        [source, source_id],
    )
    if not rows:
        raise HTTPException(404, f"No title found for {source}:{source_id}")
    return rows[0]

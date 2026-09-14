from __future__ import annotations

import duckdb
from fastapi import APIRouter, Depends, HTTPException, Query

from ..db import get_db, run_query
from ..schemas import Anime, AnimeListResponse, Franchise, FranchiseEntry
from .schedule import upcoming_episodes

router = APIRouter(prefix="/anime", tags=["anime"])

# Every sort ends with a unique tiebreaker, and that is load-bearing rather than
# tidy. Without it, ORDER BY over a large block of equal values has no defined
# order, so LIMIT/OFFSET slices a differently shuffled result on each call and
# paging silently serves some rows twice while never serving others.
#
# This was not theoretical. 103 of 142 rows have a NULL score, so under the
# default score_desc sort nearly the whole catalogue was one undifferentiated
# tie block: three identical two-page fetches returned 126, 116 and 122 distinct
# titles, differing by 30-40 ids. (source, source_id) is unique per row, so
# appending it makes every ordering total and paging reproducible.
_TIEBREAK = "source ASC, source_id ASC"

_SORT_COLUMNS = {
    "score_desc": f"score_100 DESC NULLS LAST, {_TIEBREAK}",
    "popularity_desc": f"popularity DESC NULLS LAST, {_TIEBREAK}",
    # Explicit casts: if a partition's parquet happens to hold an all-NULL
    # title_romaji, DuckDB types that column INTEGER and COALESCE refuses to mix
    # it with VARCHAR, turning the whole sort into a 500. Casting both sides
    # makes the ordering independent of how any one file's nulls were typed.
    "title": f"COALESCE(CAST(title_english AS VARCHAR), CAST(title_romaji AS VARCHAR)) ASC, {_TIEBREAK}",
}


def _build_filters(
    season: str | None,
    season_year: int | None,
    genre: str | None,
    format: str | None,
    min_score: float | None,
    studio: str | None = None,
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
    if studio:
        # The one filter a client cannot apply to a season it already holds:
        # "what else did this studio make" spans every season, and answering it
        # locally meant holding the whole catalogue. Case-insensitive like genre.
        clauses.append("EXISTS (SELECT 1 FROM UNNEST(studios) AS t(s) WHERE LOWER(s) = LOWER(?))")
        params.append(studio)

    where_sql = " AND ".join(clauses) if clauses else "TRUE"
    return where_sql, params


@router.get("", response_model=AnimeListResponse)
def list_anime(
    season: str | None = None,
    season_year: int | None = None,
    genre: str | None = None,
    format: str | None = None,
    min_score: float | None = None,
    studio: str | None = None,
    sort: str = Query("score_desc", pattern="^(score_desc|popularity_desc|title)$"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    con: duckdb.DuckDBPyConnection = Depends(get_db),
) -> AnimeListResponse:
    where_sql, params = _build_filters(season, season_year, genre, format, min_score, studio)
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


def _optional(con: duckdb.DuckDBPyConnection, sql: str, params: list) -> list[dict]:
    """A query against the identity layer, which may not exist yet.

    anime_identity and anime_alias only appear once the pipeline has run with
    identities, and anime_media_latest only has a wb_id column from then on.
    Until that first run, "no identity layer" means "nothing to resolve", not
    "the service is broken" - so an empty result, never the 503 or 500 a missing
    view or column would otherwise raise.
    """
    try:
        return con.execute(sql, params).fetch_arrow_table().to_pylist()
    except (duckdb.CatalogException, duckdb.BinderException):
        return []


def _by_identity(con: duckdb.DuckDBPyConnection, wb_id: str) -> list[dict]:
    """The current title for an identity, following it if it was since merged."""
    alias = _optional(con, "SELECT wb_id FROM anime_alias WHERE alias = ?", [wb_id])
    target = alias[0]["wb_id"] if alias else wb_id
    return _optional(con, "SELECT * FROM anime_media_latest WHERE wb_id = ?", [target])


# Declared before /{source}/{source_id}. The two cannot collide - one path
# segment against two - but this is the address new references should use.
@router.get("/{wb_id}", response_model=Anime)
def get_anime_by_identity(
    wb_id: str, con: duckdb.DuckDBPyConnection = Depends(get_db)
) -> Anime:
    """A title by its stable identity.

    Survives every change of merge winner, and resolves an identity that has
    since merged into another to the title that absorbed it - which is the whole
    reason to prefer this over /{source}/{source_id} for anything stored.
    """
    rows = _by_identity(con, wb_id)
    if not rows:
        raise HTTPException(404, f"No title with identity {wb_id}")
    return _with_airing(con, rows[0])


def _with_airing(con: duckdb.DuckDBPyConnection, row: dict) -> Anime:
    """One title, with its next episodes from AniList's schedule."""
    title = Anime(**row)
    if title.wb_id:
        title.upcoming_episodes = upcoming_episodes(con, title.wb_id)
    return title


# A link recorded on only one side reads the other way from the other side.
# parent_story is the far end of both a side story and a spin-off, and MAL does
# not say which, so the near end of a parent_story reads as a side story.
_INVERSE = {
    "prequel": "sequel", "sequel": "prequel",
    "side_story": "parent_story", "spin_off": "parent_story", "parent_story": "side_story",
    "summary": "full_story", "full_story": "summary",
    "alternative_version": "alternative_version", "alternative_setting": "alternative_setting",
    "character": "character", "other": "other",
}


def _date(row: dict) -> str | None:
    """The catalogue's own start date where it has one, as a sortable ISO string."""
    if not row.get("start_year"):
        return None
    parts = [f"{int(row['start_year']):04d}"]
    for key in ("start_month", "start_day"):  # a day means nothing without its month
        if not row.get(key):
            break
        parts.append(f"{int(row[key]):02d}")
    return "-".join(parts)


# Declared before /{source}/{source_id}, which would otherwise take
# /wb_x/franchise as source "wb_x", source_id "franchise".
@router.get("/{wb_id}/franchise", response_model=Franchise)
def get_franchise(wb_id: str, con: duckdb.DuckDBPyConnection = Depends(get_db)) -> Franchise:
    """Every title in this title's franchise, oldest first.

    Entries in the catalogue come as the catalogue has them; entries older than
    it come from MAL's description of them, with no wb_id. A title in no
    franchise - or one with no MAL id, or before any franchises are built - gets
    an empty list rather than an error: having no sequels is not a failure.
    """
    titles = _by_identity(con, wb_id)
    if not titles:
        raise HTTPException(404, f"No title with identity {wb_id}")
    mal_id = titles[0].get("mal_id")
    if mal_id is None:
        return Franchise()

    found = _optional(con, "SELECT franchise_id FROM franchise_member WHERE mal_id = ?", [mal_id])
    if not found:
        return Franchise()
    franchise_id = found[0]["franchise_id"]

    rows = _optional(
        con,
        "SELECT f.mal_id, f.title AS mal_title, f.format AS mal_format, f.start_date AS mal_start, "
        "f.poster_url AS mal_poster, m.wb_id, m.title_english, m.title_romaji, m.format, m.poster_url, "
        "m.score_100, m.season, m.season_year, m.start_year, m.start_month, m.start_day "
        "FROM franchise_member f LEFT JOIN anime_media_latest m ON m.mal_id = f.mal_id "
        "WHERE f.franchise_id = ?",
        [franchise_id],
    )
    direct = {
        r["related_mal_id"]: r["relation_type"]
        for r in _optional(con, "SELECT related_mal_id, relation_type FROM anime_relation WHERE mal_id = ?", [mal_id])
    }
    pointing_here = {
        r["mal_id"]: _INVERSE.get(r["relation_type"])
        for r in _optional(con, "SELECT mal_id, relation_type FROM anime_relation WHERE related_mal_id = ?", [mal_id])
    }

    entries = [
        FranchiseEntry(
            mal_id=r["mal_id"],
            wb_id=r["wb_id"],
            title=r["title_english"] or r["title_romaji"] or r["mal_title"],
            format=r["format"] or r["mal_format"],
            start_date=_date(r) or r["mal_start"],
            season=r["season"],
            season_year=r["season_year"],
            poster_url=r["poster_url"] or r["mal_poster"],
            score_100=r["score_100"],
            relation=direct.get(r["mal_id"]) or pointing_here.get(r["mal_id"]),
            is_this=r["mal_id"] == mal_id,
        )
        for r in rows
    ]
    entries.sort(key=lambda e: (e.start_date is None, e.start_date or "", e.title or ""))
    return Franchise(franchise_id=franchise_id, entries=entries)


@router.get("/{source}/{source_id}", response_model=Anime)
def get_anime(
    source: str, source_id: str, con: duckdb.DuckDBPyConnection = Depends(get_db)
) -> Anime:
    """A title by any source key it has ever been known by.

    This used to match only the merge's current winner, so a key that lost a
    merge - `mal:63830` folded into `kitsu:50665`, say - returned 404 for a title
    that plainly existed. Every link ever made with a losing key broke silently.
    Now a miss on the winner falls through to the identity registry, which knows
    every key a title was assembled from, and returns the title it belongs to.
    The response carries that title's own source, source_id and wb_id, so a
    caller can see it was redirected.
    """
    rows = run_query(
        con,
        "SELECT * FROM anime_media_latest WHERE source = ? AND source_id = ?",
        [source, source_id],
    )
    if rows:
        return _with_airing(con, rows[0])

    known = _optional(
        con, "SELECT wb_id FROM anime_identity WHERE source_key = ?", [f"{source}:{source_id}"]
    )
    if known:
        rows = _by_identity(con, known[0]["wb_id"])
        if rows:
            return _with_airing(con, rows[0])

    raise HTTPException(404, f"No title found for {source}:{source_id}")

from __future__ import annotations

import duckdb
from fastapi import APIRouter, Depends

from ..db import get_db, run_query
from ..schemas import CatalogueSummary, Contested
from ..seasons import QUARTER, SEASON_START

router = APIRouter(prefix="/catalogue", tags=["catalogue"])


def _sources(con: duckdb.DuckDBPyConnection) -> list[str]:
    """Every source with a row in the catalogue, read from source_keys.

    source_keys records every row that merged into a title, so it names sources
    that never won a merge. A warehouse from before identities has no such
    column; the merge winners are the best answer it can give.
    """
    try:
        rows = con.execute(
            "SELECT DISTINCT split_part(k, ':', 1) AS source "
            "FROM (SELECT UNNEST(source_keys) AS k FROM anime_media_latest) ORDER BY 1"
        ).fetchall()
        if rows:
            return [r[0] for r in rows]
    except (duckdb.CatalogException, duckdb.BinderException):
        pass
    return [r["source"] for r in run_query(con, "SELECT DISTINCT source FROM anime_media_latest ORDER BY 1")]


@router.get("", response_model=CatalogueSummary)
def catalogue(con: duckdb.DuckDBPyConnection = Depends(get_db)) -> CatalogueSummary:
    """The season list, the sources and the size of the catalogue.

    One request where a client used to need every title. Seasons are the ones
    titles are filed under - the season each premiered in - with how many titles
    each holds. Titles with no season are counted in the total and nowhere else.
    """
    total = run_query(con, "SELECT COUNT(*) AS n FROM anime_media_latest")[0]["n"]
    seasons = run_query(
        con,
        "SELECT season, season_year, COUNT(*) AS count, "
        f"  {SEASON_START} > current_date AS upcoming "
        "FROM anime_media_latest "
        "WHERE season IS NOT NULL AND season_year IS NOT NULL "
        f"GROUP BY season, season_year ORDER BY season_year DESC, {QUARTER} DESC NULLS LAST, season",
    )
    return CatalogueSummary(
        total=total, sources=_sources(con), seasons=seasons, contested=_contested(con)
    )


_CONTESTED = """
WITH raw AS (
  SELECT i.wb_id AS wb_id, x.src AS src, x.average_score AS a, x.user_count AS u
  FROM (%s) x
  JOIN anime_identity i ON i.source_key = x.src || ':' || CAST(x.source_id AS VARCHAR)
), per AS (
  SELECT wb_id, src, a FROM raw
  QUALIFY ROW_NUMBER() OVER (PARTITION BY wb_id, src ORDER BY u DESC NULLS LAST) = 1
), spread AS (
  SELECT wb_id, ROUND(MAX(a) / 10, 1) - ROUND(MIN(a) / 10, 1) AS sp
  FROM per GROUP BY 1 HAVING COUNT(*) >= 2
)
SELECT COUNT(*) AS rated_by_two, COUNT(*) FILTER (WHERE sp >= 0.2) AS differ FROM spread
"""

_SOURCE_VIEWS = {"kitsu": "anime_media_kitsu", "mal": "anime_media_mal",
                 "anilist": "anime_media_anilist"}


def _contested(con: duckdb.DuckDBPyConnection) -> Contested | None:
    """How often two sources that both scored a title print different numbers.

    Read from the per-source views rather than anime_media, which is
    CONSOLIDATED - one winning row per title per run - so measuring it there
    finds only titles whose winner changed between runs and reports 80%
    agreement about nothing.

    One reading per source, the most-voted, because these views are SELECT *
    over a glob of dated files whose date is in the FILENAME and not a column:
    there is no run_date to order by, and vote counts only accumulate.

    12 ms warm over 40 seasons, against a response the frontend caches for an
    hour, so it is paid about once a visit rather than once a page.
    """
    present = {
        r[0] for r in con.execute(
            "SELECT table_name FROM duckdb_tables() UNION SELECT view_name FROM duckdb_views()"
        ).fetchall()
    }
    usable = [(s, v) for s, v in _SOURCE_VIEWS.items() if v in present]
    if len(usable) < 2:
        return None  # nothing can disagree with itself

    union = " UNION ALL ".join(
        f"SELECT '{source}' AS src, source_id, average_score, user_count "
        f"FROM {view} WHERE average_score IS NOT NULL"
        for source, view in usable
    )
    try:
        row = con.execute(_CONTESTED % union).fetchone()
    except duckdb.Error:
        return None
    return Contested(rated_by_two=row[0], differ=row[1]) if row and row[0] else None

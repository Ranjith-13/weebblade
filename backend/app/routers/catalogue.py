from __future__ import annotations

import duckdb
from fastapi import APIRouter, Depends

from ..db import get_db, run_query
from ..schemas import CatalogueSummary

router = APIRouter(prefix="/catalogue", tags=["catalogue"])

# The broadcast year runs Winter, Spring, Summer, Fall. Sorted alphabetically,
# Fall would come first in a year and Summer after Spring only by luck.
_QUARTER = "CASE season WHEN 'WINTER' THEN 0 WHEN 'SPRING' THEN 1 WHEN 'SUMMER' THEN 2 WHEN 'FALL' THEN 3 END"


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
        "SELECT season, season_year, COUNT(*) AS count FROM anime_media_latest "
        "WHERE season IS NOT NULL AND season_year IS NOT NULL "
        f"GROUP BY season, season_year ORDER BY season_year DESC, {_QUARTER} DESC NULLS LAST, season",
    )
    return CatalogueSummary(total=total, sources=_sources(con), seasons=seasons)

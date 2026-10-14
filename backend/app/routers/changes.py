from __future__ import annotations

import logging
from datetime import date, timedelta

import duckdb
from fastapi import APIRouter, Depends, Query

from ..db import get_db
from ..schemas import Change, ChangedTitle, ChangeFeed

router = APIRouter(prefix="/changes", tags=["changes"])
logger = logging.getLogger(__name__)

# The merge's source priority, which is also the order a change's sources are
# listed in; and the order a title's changes on one date are listed in.
_SOURCES = ["kitsu", "mal", "anilist"]
_FIELDS = ["status", "episodes", "premiere", "season", "broadcast", "score", "trailer", "streaming", "listed"]

# One change reported by several sources in the same fetch is one change. Kitsu
# and MAL both saying a show finished is the same news, told twice.
_GROUPED = (
    "SELECT wb_id, field, old, new, run_date, ANY_VALUE(label) AS label, MIN(since) AS since, "
    "LIST(DISTINCT source) AS sources FROM anime_change WHERE {where} "
    "GROUP BY wb_id, field, old, new, run_date"
)


def _read(con: duckdb.DuckDBPyConnection, sql: str, params: list) -> list[dict]:
    """A query against anime_change, which exists once a run has recorded
    changes. Before that there is nothing to report, not an error."""
    try:
        return con.execute(sql, params).fetch_arrow_table().to_pylist()
    except duckdb.CatalogException:
        return []


def _ranked(sources: list[str]) -> list[str]:
    return sorted(sources, key=lambda s: _SOURCES.index(s) if s in _SOURCES else len(_SOURCES))


def _order(field: str) -> int:
    return _FIELDS.index(field) if field in _FIELDS else len(_FIELDS)


def title_changes(con: duckdb.DuckDBPyConnection, wb_id: str) -> list[Change]:
    """A title's changes, newest first. A title page must never fail because of
    its history, so any failure costs the page that list, logged, and no more."""
    try:
        rows = _read(con, _GROUPED.format(where="wb_id = ?"), [wb_id])
    except duckdb.Error:
        logger.warning("Could not read changes for %s", wb_id, exc_info=True)
        return []
    rows.sort(key=lambda r: (_order(r["field"]), r["new"] or ""))
    rows.sort(key=lambda r: r["run_date"], reverse=True)
    return [Change(**{**r, "sources": _ranked(r["sources"])}) for r in rows]


@router.get("", response_model=ChangeFeed)
def changes(
    days: int = Query(7, ge=1, le=90),
    con: duckdb.DuckDBPyConnection = Depends(get_db),
) -> ChangeFeed:
    """Every change recorded in the `days` days up to the newest fetch compared,
    on the titles the catalogue serves.

    Counted back from the newest fetch, not from today, so the week a weekly
    run covers stays whole until the next one replaces it."""
    newest = _read(con, "SELECT MAX(run_date) AS d FROM anime_change", [])
    until = newest[0]["d"] if newest else None
    if until is None:
        return ChangeFeed()

    since = (date.fromisoformat(until) - timedelta(days=days)).isoformat()
    grouped = _GROUPED.format(where="run_date > ?")
    rows = _read(
        con,
        # Cast: a title column null in every row of a snapshot reads as INTEGER,
        # and the DuckDB CI pins refuses to COALESCE that with VARCHAR.
        f"SELECT c.*, COALESCE(CAST(m.title_english AS VARCHAR), CAST(m.title_romaji AS VARCHAR)) AS title, "
        f"m.format, m.poster_url, m.season, m.season_year "
        f"FROM ({grouped}) c JOIN anime_media_latest m ON m.wb_id = c.wb_id",
        [since],
    )
    # By kind of change, newest first within each, then by title.
    rows.sort(key=lambda r: (r["title"] or "", r["new"] or ""))
    rows.sort(key=lambda r: r["run_date"], reverse=True)
    rows.sort(key=lambda r: _order(r["field"]))
    return ChangeFeed(
        since=since,
        until=until,
        changes=[ChangedTitle(**{**r, "sources": _ranked(r["sources"])}) for r in rows],
    )

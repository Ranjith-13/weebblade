"""AniList's own status for the titles the catalogue says are airing.

A title page with no AniList airdate falls back to MAL's weekly broadcast
slot, and a slot is only true while a show is airing. The catalogue's status
cannot say when that stops. It is the merge winner's - Kitsu's, mostly - as of
the snapshot the title was filed in, and only the current season is refetched:
on 2026-09-14 the catalogue called 79 titles airing that AniList had as
finished, some of them for a year or more, and the page counted those with a
MAL slot down to one that would not come again.

So each day this asks AniList about exactly the titles the catalogue calls
airing, and the page believes AniList when it says a show has stopped. The
rest need no asking: a title the catalogue already calls finished shows no
slot on its own account. The first check asked about 288 titles in seven
requests; AniList answered for 241 and had 79 of them finished, 34 with a MAL
slot the page was counting down to - Yu-Gi-Oh! Go Rush!!, finished in March
2025, among them.

Titles are asked about by AniList id where the catalogue has one, and by MAL
id where it has only that.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import duckdb
import pyarrow as pa

from ..storage import write_daily, write_raw_json
from .client import AniListClient

logger = logging.getLogger(__name__)

CHUNK = 50

_FIELDS = "id idMal status endDate { year month day }"
BY_ANILIST_ID = (
    "query ($ids: [Int]) { Page(perPage: 50) { media(id_in: $ids, type: ANIME) { " + _FIELDS + " } } }"
)
BY_MAL_ID = (
    "query ($ids: [Int]) { Page(perPage: 50) { media(idMal_in: $ids, type: ANIME) { " + _FIELDS + " } } }"
)

# AniList's words, in the shared vocabulary where it has one. This is AniList's
# own account of a title rather than a column of the merged catalogue, so the
# two states the catalogue has no word for are kept rather than dropped: a show
# on hiatus is not airing, and that is exactly what the page needs to know.
_STATUSES = {
    "FINISHED": "finished",
    "RELEASING": "current",
    "NOT_YET_RELEASED": "upcoming",
    "CANCELLED": "cancelled",
    "HIATUS": "hiatus",
}

SCHEMA = pa.schema(
    [
        ("anilist_id", pa.int64()),
        ("mal_id", pa.int64()),
        ("status", pa.string()),
        # ISO, as much of it as AniList knows: "2026-09-10", "2026-09", "2026".
        ("ended_on", pa.string()),
        ("fetched_on", pa.string()),
    ]
)


def candidates(db_path: Path) -> tuple[list[int], list[int]]:
    """AniList ids, and MAL ids for titles with no AniList id, of every title the
    sources call airing. Read-only: the warehouse is only looked at.

    The sources' status, merged_status, and not the status the warehouse serves,
    which this check itself corrects. Asked by the corrected one, a title AniList
    called finished yesterday would not be asked about today, would read as
    airing again tomorrow, and would be asked again the day after - flipping
    every day for as long as the sources lag."""
    con = duckdb.connect(str(db_path), read_only=True)
    try:
        columns = {row[0] for row in con.execute("DESCRIBE anime_media_latest").fetchall()}
        status = "merged_status" if "merged_status" in columns else "status"
        rows = con.execute(
            f"SELECT source_keys, mal_id FROM anime_media_latest WHERE {status} = 'current'"
        ).fetchall()
    finally:
        con.close()

    anilist: set[int] = set()
    mal_only: set[int] = set()
    for keys, mal_id in rows:
        ids = {int(k.split(":", 1)[1]) for k in keys or [] if k.startswith("anilist:")}
        if ids:
            anilist |= ids
        elif mal_id is not None:
            mal_only.add(int(mal_id))
    return sorted(anilist), sorted(mal_only)


def fetch_status(
    anilist_ids: list[int], mal_ids: list[int], client: AniListClient | None = None
) -> list[dict[str, Any]]:
    """AniList's record of each title asked about, once each."""
    client = client or AniListClient()
    found: dict[int, dict[str, Any]] = {}
    for query, ids in ((BY_ANILIST_ID, anilist_ids), (BY_MAL_ID, mal_ids)):
        for i in range(0, len(ids), CHUNK):
            for media in client.query(query, {"ids": ids[i : i + CHUNK]})["Page"]["media"]:
                found.setdefault(media["id"], media)
    return list(found.values())


def _ended_on(end: dict[str, Any] | None) -> str | None:
    end = end or {}
    parts = [f"{end['year']:04d}"] if end.get("year") else []
    for key in ("month", "day"):  # a day means nothing without its month
        if not parts or not end.get(key):
            break
        parts.append(f"{end[key]:02d}")
    return "-".join(parts) or None


def flatten_status(media: dict[str, Any], fetched_on: str) -> dict[str, Any]:
    return {
        "anilist_id": media["id"],
        "mal_id": media.get("idMal"),
        "status": _STATUSES.get(media.get("status") or ""),
        "ended_on": _ended_on(media.get("endDate")),
        "fetched_on": fetched_on,
    }


def land_status(data_dir: Path, run_date: str, client: AniListClient | None = None) -> int:
    """Ask about today's airing titles, land the answers raw and processed."""
    anilist_ids, mal_ids = candidates(data_dir / "warehouse.duckdb")
    raw = fetch_status(anilist_ids, mal_ids, client)
    write_raw_json(raw, data_dir / "raw" / "anilist_status", run_date)

    rows = [flatten_status(m, run_date) for m in raw]
    write_daily(rows, SCHEMA, data_dir, "anilist_status", run_date)
    logger.info(
        "AniList status: asked about %s titles (%s by MAL id), %s answered",
        len(anilist_ids) + len(mal_ids), len(mal_ids), len(rows),
    )
    return len(rows)

"""AniList's own status for the titles the catalogue says are airing.

A title page with no AniList airdate falls back to MAL's weekly broadcast
slot, and a slot is only true while a show is airing. The catalogue's status
cannot say when that stops. It is the merge winner's - Kitsu's, mostly - as of
the snapshot the title was filed in, and only the current season is refetched:
on 2026-09-14 the catalogue called 79 titles airing that AniList had as
finished, some of them for a year or more, and the page counted those with a
MAL slot down to one that would not come again.

So each day this asks AniList about exactly the titles the sources call
airing, and the warehouse believes AniList when it says a show has stopped
(processing/duckdb_catalog._status_corrected). The rest need no asking: a
title the sources already call finished is finished everywhere. The first check asked about 288 titles in seven
requests; AniList answered for 241 and had 79 of them finished, 34 with a MAL
slot the page was counting down to - Yu-Gi-Oh! Go Rush!!, finished in March
2025, among them.

Titles are asked about by AniList id where the catalogue has one, by MAL id
where it has only that, and by an id found for it by search where it has
neither that works - see ingestion/anilist/resolve_ids.py, which is what asks
about the 67 titles this had no way to reach.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import duckdb
import pyarrow as pa

from ..storage import write_daily, write_raw_json
from .client import AniListClient
from .resolve_ids import RETRY_DAYS, resolved_ids, searched_and_missed

logger = logging.getLogger(__name__)

CHUNK = 50

# averageScore and popularity ride along on a request that was already being
# made. The weekly pipeline refetches a season once every seven days, so a score
# that moves twice in a week is recorded as one move and anything inside the week
# is simply not there - and movement DURING a season is the whole subject of
# /scores, which measured 35% of readings of an airing season changing against 1%
# of a finished one. This check already asks AniList about exactly the titles
# that are airing, every morning, so the dense half of that series costs two
# more fields on an existing query and no extra requests at all.
#
# popularity is not decoration either. /scores counts a pair of readings only
# where the source's own vote count moved, because a detector that looks at the
# score throws away every reading that came back the same and reports movement
# near 100% by construction. AniList's popularity is that vote count: the number
# of users holding the title on a list. Without it a daily series cannot tell a
# score that was re-asked and did not move from one that was never asked.
_FIELDS = "id idMal status averageScore popularity endDate { year month day }"
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
        # AniList's averageScore is already out of 100, which is the scale the
        # warehouse stores and /10 is only ever a display concern. Null for a
        # title nobody has rated yet, which is most of a premiere week.
        ("score_100", pa.int64()),
        # AniList's popularity: users holding the title on a list. The movement
        # detector, not a statistic to print - see the note above _FIELDS.
        ("user_count", pa.int64()),
        # ISO, as much of it as AniList knows: "2026-09-10", "2026-09", "2026".
        ("ended_on", pa.string()),
        ("fetched_on", pa.string()),
    ]
)


# How long after its last episode a title is still worth asking about daily.
#
# THE SEASON JUST ENDED IS WHERE SCORES MOVE MOST, and until this it was the one
# cohort nobody asked about. Measured over the catalogue's own history: 51% of
# the airing season's TV titles had visibly moved their score, against 71% of
# the season just ended - the votes keep arriving for weeks after a finale and
# the average is still settling. Asking only about titles the sources call
# current stopped watching each show at exactly the point it moves fastest.
#
# Defined by the archive rather than by season arithmetic. "The season just
# ended" is a human phrase and a nuisance to compute - seasons are quarters, a
# show can be filed under the quarter it began and finish two quarters later -
# while "an episode went out recently" is a fact anime_airing_history already
# holds, per title, with no calendar reasoning at all.
#
# 45 days because that is where it stops adding anyone: measured on 2026-10-19,
# 30 days brings 49 extra titles, 45 brings 58 and 60 brings the same 58. It is
# 58 against the 347 already asked about, which at AniList's 50 ids a page is
# one more request on a daily run that spends seven.
RECENT_DAYS = 45


def _recently_aired(con: duckdb.DuckDBPyConnection, wb_id: str) -> str:
    """The predicate that keeps a just-finished show in the cohort, or a
    constant false where it cannot be evaluated.

    anime_airing_history arrived with the episode archive and is absent from any
    warehouse built before it, and a title with no identity has no wb_id to be
    matched on. Either way the answer is the cohort as it always was: the titles
    the sources call current. A missing view must not take the status check
    down - it is the only thing correcting a finished show's status, and 986
    finished titles once counted down to a slot for a series that was over.
    """
    if wb_id == "NULL":
        return "FALSE"
    try:
        con.execute("SELECT 1 FROM anime_airing_history LIMIT 1")
    except duckdb.Error:
        logger.info("No episode archive yet - asking only about titles the sources call current")
        return "FALSE"
    return (
        "wb_id IN (SELECT wb_id FROM anime_airing_history WHERE wb_id IS NOT NULL "
        f"AND to_timestamp(airing_at) BETWEEN now() - INTERVAL {RECENT_DAYS} DAY AND now())"
    )


def candidates(data_dir: Path) -> tuple[list[int], list[int]]:
    """AniList ids, and MAL ids for titles with no AniList id, of every title the
    sources call airing. Read-only: the warehouse is only looked at.

    A title with neither - or with a MAL id no AniList entry claims - may still
    have been found by title search, and its id is used here the day it is
    found, rather than waiting for the weekly refresh that puts it in a view.

    The sources' status, merged_status, and not the status the warehouse serves,
    which this check itself corrects. Asked by the corrected one, a title AniList
    called finished yesterday would not be asked about today, would read as
    airing again tomorrow, and would be asked again the day after - flipping
    every day for as long as the sources lag."""
    con = duckdb.connect(str(data_dir / "warehouse.duckdb"), read_only=True)
    try:
        columns = {row[0] for row in con.execute("DESCRIBE anime_media_latest").fetchall()}
        status = "merged_status" if "merged_status" in columns else "status"
        wb_id = "wb_id" if "wb_id" in columns else "NULL"
        rows = con.execute(
            f"SELECT {wb_id}, source_keys, mal_id FROM anime_media_latest "
            f"WHERE {status} = 'current' OR {_recently_aired(con, wb_id)}"
        ).fetchall()
    finally:
        con.close()

    found = resolved_ids(data_dir)
    missed = searched_and_missed(data_dir)
    anilist: set[int] = set()
    mal_only: set[int] = set()
    futile = 0
    for wb_id, keys, mal_id in rows:
        ids = {int(k.split(":", 1)[1]) for k in keys or [] if k.startswith("anilist:")}
        searched = found.get(wb_id)
        if searched is not None:
            ids.add(int(searched))
        if ids:
            anilist |= ids
        elif mal_id is not None:
            mal_only.add(int(mal_id))
            if wb_id in missed:
                futile += 1
    if futile:
        # Reported, not predicted. These have been searched by NAME and not
        # found, which is a different question from whether AniList has an
        # entry carrying their MAL id - the strict matching rules refuse an
        # ambiguous name that idMal answers for anyway. On 2026-10-18, 88
        # titles here were name-search misses and 78 went unanswered, so ten
        # of them were answered by id. land_status counts what actually came
        # back; this only says how many were already known to be hard.
        logger.info(
            "Of the %s asked by MAL id, %s have also been searched by name without "
            "finding an AniList entry (retried every %s days).",
            len(mal_only), futile, RETRY_DAYS,
        )
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
        "score_100": media.get("averageScore"),
        "user_count": media.get("popularity"),
        "ended_on": _ended_on(media.get("endDate")),
        "fetched_on": fetched_on,
    }


def land_status(data_dir: Path, run_date: str, client: AniListClient | None = None) -> int:
    """Ask about today's airing titles, land the answers raw and processed."""
    anilist_ids, mal_ids = candidates(data_dir)
    raw = fetch_status(anilist_ids, mal_ids, client)
    write_raw_json(raw, data_dir / "raw" / "anilist_status", run_date)

    rows = [flatten_status(m, run_date) for m in raw]
    write_daily(rows, SCHEMA, data_dir, "anilist_status", run_date)

    # WHY THE TWO NUMBERS DIFFER, said here rather than left as a subtraction.
    # "asked about 435 titles, 357 answered" reads like 78 failures and is not
    # one: a title with no AniList key is asked about by its MAL id, and where
    # no AniList entry carries that idMal there is simply nothing to return.
    # Every one of the 78 on 2026-10-18 was that, and establishing it cost an
    # hour of reading parquet. Counted from the answers rather than guessed at
    # beforehand, because only the response knows which ids landed.
    answered_mal = {m.get("idMal") for m in raw if m.get("idMal") is not None}
    unanswered = len([i for i in mal_ids if i not in answered_mal])
    logger.info(
        "AniList status: asked about %s titles (%s by MAL id), %s answered",
        len(anilist_ids) + len(mal_ids), len(mal_ids), len(rows),
    )
    if unanswered:
        logger.info(
            "AniList status: %s of the %s asked by MAL id went unanswered - AniList "
            "carries no entry with that id. Not a failure; see ingestion/anilist/"
            "resolve_ids.py, which searches such titles by name and records the misses.",
            unanswered, len(mal_ids),
        )
    return len(rows)

"""AniList ids for the airing titles the daily check cannot ask about.

The status check asks AniList about a title by its AniList id, or by its MAL id
where the catalogue has only that (ingestion/anilist/fetch_status.py). 67 titles
the sources call airing have neither that works: 48 carry a MAL id AniList does
not answer for, because no AniList entry claims that id, and 19 carry no usable
id at all - Kitsu-only listings, mostly obscure ONAs. 48 of the 67 premiered
over a year ago, and nothing can check whether they are still airing, so the
catalogue goes on calling them airing on the strength of a snapshot that may be
years old.

So each day this searches AniList by title for a few of them and remembers what
it found, which turns "we cannot ask" into either an id to ask by from then on,
or a recorded fact that AniList has no such entry.

A search returns near misses by design, so a hit is accepted only on the same
rules that decide two source rows are one title (processing/matching.py): an
exact title plus format and year, or an exact title plus the exact premiere
date. They are strict because the cost of being wrong is high - a wrong id
here would put another show's status on this title - and being unable to
confirm is the state we are already in, so a refused match loses nothing.

Two entries matching is a refusal too, for the reason matching.py refuses a key
naming two works: there is no way to choose, and guessing is how one title
becomes another.

The searches are capped per run and never repeated within RETRY_DAYS, so the
first run spends 60 requests and later ones almost none. A miss is recorded and
retried monthly: AniList gains entries, and a title it does not know today may
be there next month.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq

from processing import matching

from .client import AniListClient
from .transform import _FORMATS

logger = logging.getLogger(__name__)

# One request each, at AniList's 30 a minute. The first run has 67 to get
# through and takes the rest tomorrow rather than holding the DAG for minutes.
BUDGET = 60

# How long a search result stands before it is asked again. Only misses are ever
# re-asked; a match becomes an id the status check uses from then on.
RETRY_DAYS = 30

# Five, not one: AniList ranks by its own relevance, and the exact title is not
# always first - it puts a sequel or a compilation film above the entry whose
# name was typed. The rules below decide which of the five is the title, if any.
SEARCH = """
query ($q: String) {
  Page(perPage: 5) {
    media(search: $q, type: ANIME) {
      id
      idMal
      title { romaji english }
      format
      seasonYear
      startDate { year month day }
    }
  }
}
"""

SCHEMA = pa.schema(
    [
        ("wb_id", pa.string()),
        # Null for a title AniList has no entry for, which is a result: it says
        # this title cannot be confirmed by anyone, rather than leaving it to be
        # searched for again tomorrow.
        ("anilist_id", pa.int64()),
        # The matching rule that accepted the entry - "romaji", "display" or
        # "premiere" - or why it was refused: "no match", "ambiguous".
        ("matched_by", pa.string()),
        ("title", pa.string()),
        ("searched_on", pa.string()),
    ]
)

# The columns matching.keys() reads, and the ones a search answer can fill.
_TITLE_RULES = ("romaji", "display", "premiere")

_CANDIDATES = """
    SELECT wb_id, title_english, title_romaji, format, season_year,
           start_year, start_month, start_day
    FROM anime_media_latest
    WHERE merged_status = 'current' AND anilist_status IS NULL AND wb_id IS NOT NULL
    ORDER BY wb_id
"""


def _searched_recently(data_dir: Path, run_date: str) -> set[str]:
    """Every title searched within RETRY_DAYS of this run, matched or not."""
    files = sorted((data_dir / "processed" / "anilist_resolved").glob("*.parquet"))
    if not files:
        return set()
    cutoff = (date.fromisoformat(run_date) - timedelta(days=RETRY_DAYS)).isoformat()
    con = duckdb.connect()
    try:
        rows = con.execute(
            f"SELECT DISTINCT wb_id FROM read_parquet({[str(p) for p in files]}) "
            "WHERE searched_on > ?",
            [cutoff],
        ).fetchall()
    finally:
        con.close()
    return {row[0] for row in rows}


def unresolved(data_dir: Path, run_date: str) -> list[dict[str, Any]]:
    """Titles the sources call airing that AniList has not answered for, minus
    the ones already searched for recently. Read-only: the warehouse is only
    looked at, and the daily DAG never writes it."""
    db_path = data_dir / "warehouse.duckdb"
    if not db_path.exists():
        return []
    con = duckdb.connect(str(db_path), read_only=True)
    try:
        rows = con.execute(_CANDIDATES).fetch_arrow_table().to_pylist()
    except duckdb.CatalogException:  # no catalogue yet, or no status check run
        return []
    finally:
        con.close()

    skip = _searched_recently(data_dir, run_date)
    return [row for row in rows if row["wb_id"] not in skip]


def _media_row(media: dict[str, Any]) -> dict[str, Any]:
    """A search answer in the vocabulary matching.keys() reads."""
    start = media.get("startDate") or {}
    title = media.get("title") or {}
    return {
        "source": "anilist",
        "source_id": str(media["id"]),
        "mal_id": media.get("idMal"),
        "title_romaji": title.get("romaji"),
        "title_english": title.get("english"),
        "format": _FORMATS.get(media.get("format") or ""),
        "season_year": media.get("seasonYear"),
        "start_year": start.get("year"),
        "start_month": start.get("month"),
        "start_day": start.get("day"),
    }


def match(row: dict[str, Any], media: list[dict[str, Any]]) -> tuple[int | None, str]:
    """The one entry that is this title, and the rule that says so.

    The catalogue row keeps season_year while an AniList entry has both that and
    a premiere date, so every rule the two share is tried; the title rules only,
    because a shared MAL id would already have been answered by the status
    check's own query.
    """
    wanted = {key for rule, key in matching.keys(row) if rule in _TITLE_RULES}
    if not wanted:
        return None, "unmatchable"  # no format, year or full date to match on

    hits = {}
    for entry in media:
        for rule, key in matching.keys(_media_row(entry)):
            if rule in _TITLE_RULES and key in wanted:
                hits.setdefault(entry["id"], rule)
                break

    if not hits:
        return None, "no match"
    if len(hits) > 1:
        # Two entries under one name: a series and its recap, usually. Refused
        # for the same reason matching.py refuses such a key.
        return None, "ambiguous"
    [(anilist_id, rule)] = hits.items()
    return anilist_id, rule


def _query_title(row: dict[str, Any]) -> str | None:
    return row.get("title_english") or row.get("title_romaji")


def land_resolved(
    data_dir: Path, run_date: str, budget: int = BUDGET, client: AniListClient | None = None
) -> int:
    """Search for as many unresolved titles as the budget allows, and write down
    what was found. Returns how many gained an id."""
    candidates = unresolved(data_dir, run_date)
    if not candidates:
        logger.info("AniList ids: nothing left to resolve")
        return 0

    client = client or AniListClient()
    rows = []
    for row in candidates[:budget]:
        query = _query_title(row)
        if not query:
            continue
        media = client.query(SEARCH, {"q": query})["Page"]["media"]
        anilist_id, rule = match(row, media)
        rows.append(
            {
                "wb_id": row["wb_id"],
                "anilist_id": anilist_id,
                "matched_by": rule,
                "title": query,
                "searched_on": run_date,
            }
        )

    if not rows:
        return 0

    out_dir = data_dir / "processed" / "anilist_resolved"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{run_date}.parquet"

    # Added to the day's file, not written over it. A day can search twice - a
    # retry, a manual run, an Airflow rerun - and the second overwriting the
    # first threw away what the first had learned, so those titles looked
    # unsearched again and were searched again: 60 requests spent on 2026-09-22
    # repeating 2026-09-21's work. Newest answer per title wins.
    kept = {row["wb_id"]: row for row in (pq.read_table(path).to_pylist() if path.exists() else [])}
    kept.update({row["wb_id"]: row for row in rows})

    tmp = path.with_name(path.name + ".tmp")
    pq.write_table(pa.Table.from_pylist([kept[k] for k in sorted(kept)], schema=SCHEMA), tmp)
    tmp.replace(path)

    found = sum(1 for row in rows if row["anilist_id"] is not None)
    logger.info(
        "AniList ids: searched %s of %s unresolved titles, %s matched (%s left for next run)",
        len(rows), len(candidates), found, max(0, len(candidates) - len(rows)),
    )
    return found


def searched_and_missed(data_dir: Path) -> set[str]:
    """Titles searched by name and not found on AniList, newest answer per title.

    The counterpart to resolved_ids below, and it exists so the status check can
    say WHY it will go unanswered. A title with no AniList key is asked about by
    its MAL id, AniList has no entry carrying that idMal, and the fetch returns
    nothing - which in a log reads exactly like a failure. On 2026-10-18 that
    was 78 of the 161 asked by MAL id, every one of them already searched here
    and recorded as a miss, and the shape of it ("asked about 435, 357
    answered") cost an hour to establish.

    Read from the files rather than the warehouse view, and that is not a style
    choice: anime_anilist_resolved is declared WHERE anilist_id IS NOT NULL -
    matches only - so a miss cannot appear in it by construction and a query
    against it returns zero however many were recorded. That exact mistake was
    made while diagnosing this.

    A miss is not permanent. It is retried after RETRY_DAYS, so this set is what
    is known today rather than a verdict.
    """
    files = sorted((data_dir / "processed" / "anilist_resolved").glob("*.parquet"))
    if not files:
        return set()
    con = duckdb.connect()
    try:
        rows = con.execute(
            f"SELECT wb_id FROM read_parquet({[str(p) for p in files]}) "
            "QUALIFY ROW_NUMBER() OVER (PARTITION BY wb_id ORDER BY searched_on DESC) = 1 "
            "AND anilist_id IS NULL"
        ).fetchall()
    finally:
        con.close()
    return {wb_id for (wb_id,) in rows}


def resolved_ids(data_dir: Path) -> dict[str, int]:
    """Every title that has been given an AniList id by search, newest answer
    per title. Read straight from the files rather than the warehouse view, so
    the status check can use an id the day it is found rather than waiting for
    the weekly refresh that makes the view."""
    files = sorted((data_dir / "processed" / "anilist_resolved").glob("*.parquet"))
    if not files:
        return {}
    con = duckdb.connect()
    try:
        rows = con.execute(
            f"SELECT wb_id, anilist_id FROM read_parquet({[str(p) for p in files]}) "
            "WHERE anilist_id IS NOT NULL "
            "QUALIFY ROW_NUMBER() OVER (PARTITION BY wb_id ORDER BY searched_on DESC) = 1"
        ).fetchall()
    finally:
        con.close()
    return {wb_id: anilist_id for wb_id, anilist_id in rows}

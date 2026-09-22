"""The MAL id AniList holds for a row whose own sources are silent or wrong.

A title the catalogue holds twice can only survive where its Kitsu row carries
no MAL id: with one, matching.py's first rule would already have joined it to
its MAL twin. 600 titles are in that position, and searching AniList for every
one of them (2026-09-22) found 163 entries by the project's own matching rules,
17 of which carry a MAL id another catalogue title already owns. Eleven of those
are the same work under two names - Zhu Xian Final and Jade Dynasty Final
Season, Xingchen Bian 6 and Stellar Transformation 6th Season, The Magic Chef of
Fire and Ice and The Magic Chef of Ice and Fire - each a pair no rule here can
match, because one side is a romanised Chinese title and the other its English
name, or one says "2" where the other says "2nd Season", or a `special` faces a
`music` PV.

AniList bridges them: it holds both names, and its entry carries the MAL id.

It also asks about rows whose MAL id looks wrong - one whose own MAL row
premiered months away under another name, which is how Kitsu's mapping of Yao
Shen Ji 6 to season 7's id was caught. Those rows are chosen by
processing/bridge.doubtful_mappings.

This records what AniList says and nothing more. Whether a recorded id is acted
on is processing/bridge.py's decision, kept apart deliberately - six of the
seventeen must be refused, and three of those are AniList's own stale
cross-references, where a sequel's entry carries an earlier season's MAL id:
Throne of Seal 3 under Throne of Seal 2nd Season's, two and a half years apart.
A record of what was said stays true whatever the rule for using it becomes.

Budgeted and never repeated within RETRY_DAYS, like resolve_ids, whose search
and matching this reuses. After the first pass there are only the few titles a
week that arrive with no MAL id.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq

from .client import AniListClient
from .resolve_ids import SEARCH, match

logger = logging.getLogger(__name__)

BUDGET = 60
RETRY_DAYS = 30

SCHEMA = pa.schema(
    [
        # The row this is about, as "kitsu:49307". A title of several Kitsu rows
        # needs only one of them: the rest are already grouped with it, so one
        # MAL id pulls the whole group into the merge.
        ("source_key", pa.string()),
        ("anilist_id", pa.int64()),
        # The id AniList's entry carries, which is the whole point of asking.
        # Null where the entry has none, or where nothing matched.
        ("mal_id", pa.int64()),
        ("matched_by", pa.string()),
        ("title", pa.string()),
        ("searched_on", pa.string()),
    ]
)

_LEDGER = "anilist_bridge"

_CANDIDATES = """
    SELECT source || ':' || source_id AS source_key, title_english, title_romaji, format,
           season_year, start_year, start_month, start_day
    FROM anime_media_latest
    WHERE mal_id IS NULL AND source_id IS NOT NULL
    ORDER BY source_key
"""


def _ledger_files(data_dir: Path) -> list[Path]:
    return sorted((data_dir / "processed" / _LEDGER).glob("*.parquet"))


def _searched_recently(data_dir: Path, run_date: str) -> set[str]:
    files = _ledger_files(data_dir)
    if not files:
        return set()
    cutoff = (date.fromisoformat(run_date) - timedelta(days=RETRY_DAYS)).isoformat()
    con = duckdb.connect()
    try:
        rows = con.execute(
            f"SELECT DISTINCT source_key FROM read_parquet({[str(p) for p in files]}) "
            "WHERE searched_on > ?",
            [cutoff],
        ).fetchall()
    finally:
        con.close()
    return {row[0] for row in rows}


def unsearched(data_dir: Path, run_date: str) -> list[dict[str, Any]]:
    """Rows worth asking AniList about, that have not been asked about recently:
    those with no MAL id, and those whose MAL id looks wrong."""
    from processing.bridge import doubtful_mappings

    rows: dict[str, dict[str, Any]] = {}
    db_path = data_dir / "warehouse.duckdb"
    if db_path.exists():
        con = duckdb.connect(str(db_path), read_only=True)
        try:
            rows = {r["source_key"]: r for r in con.execute(_CANDIDATES).fetch_arrow_table().to_pylist()}
        except duckdb.CatalogException:  # no catalogue yet
            pass
        finally:
            con.close()

    # A doubtful mapping is a question about one source row, so it is keyed by
    # that row rather than by whichever row won a merge.
    for row in doubtful_mappings(data_dir):
        rows.setdefault(row["source_key"], row)

    skip = _searched_recently(data_dir, run_date)
    return [rows[key] for key in sorted(rows) if key not in skip]


def land_bridge(
    data_dir: Path, run_date: str, budget: int = BUDGET, client: AniListClient | None = None
) -> int:
    """Search for as many unsearched titles as the budget allows, and write down
    the MAL id AniList holds for each. Returns how many gained one."""
    candidates = unsearched(data_dir, run_date)
    if not candidates:
        logger.info("MAL ids by AniList: nothing left to search for")
        return 0

    client = client or AniListClient()
    rows = []
    for row in candidates[:budget]:
        query = row.get("title_english") or row.get("title_romaji")
        if not query:
            continue
        media = client.query(SEARCH, {"q": query})["Page"]["media"]
        anilist_id, rule = match(row, media)
        entry = next((m for m in media if m["id"] == anilist_id), None)
        rows.append(
            {
                "source_key": row["source_key"],
                "anilist_id": anilist_id,
                "mal_id": (entry or {}).get("idMal"),
                "matched_by": rule,
                "title": query,
                "searched_on": run_date,
            }
        )

    if not rows:
        return 0

    out_dir = data_dir / "processed" / _LEDGER
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{run_date}.parquet"
    # Added to the day's file rather than written over it, for the reason
    # resolve_ids.land_resolved keeps its own day's answers.
    kept = {r["source_key"]: r for r in (pq.read_table(path).to_pylist() if path.exists() else [])}
    kept.update({r["source_key"]: r for r in rows})

    tmp = path.with_name(path.name + ".tmp")
    pq.write_table(pa.Table.from_pylist([kept[k] for k in sorted(kept)], schema=SCHEMA), tmp)
    tmp.replace(path)

    found = sum(1 for r in rows if r["mal_id"] is not None)
    logger.info(
        "MAL ids by AniList: searched %s of %s, %s carry a MAL id (%s left for the next run)",
        len(rows), len(candidates), found, max(0, len(candidates) - len(rows)),
    )
    return found

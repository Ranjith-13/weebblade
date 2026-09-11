"""MAL's related titles for every catalogue title: the edges of the franchise graph.

MAL lists a title's sequels, prequels, side stories and alternative versions on
its own detail endpoint and nowhere else - the season listing the rest of
ingestion reads does not carry them. So this is one request per title: about
5,500 for the catalogue as it stands, some 75 minutes at MAL's pace, once.

After that a run fetches only what can have changed: titles never fetched, and
titles still airing or not yet aired, which is where sequels get announced. A
finished show's list grows only when something new is related to it, and that
new title's own list names it, so the edge arrives from the other end.

Each related title comes with its own title, poster, format and start date -
MAL answers nested fields - so a franchise entry older than the catalogue can
still be drawn and dated without a request of its own.

Resumable. Each chunk of titles lands as its own raw and processed file the
moment it is fetched, and a rerun skips what already landed that day, so an
interrupted fetch loses one chunk rather than the hour.
"""

from __future__ import annotations

import argparse
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
import requests

from .client import MAL_API_URL, MalClient
from .transform import _MEDIA_TYPES

logger = logging.getLogger(__name__)

_NODE = "id,title,main_picture,media_type,start_date"
FIELDS = f"{_NODE},related_anime{{relation_type,node{{{_NODE}}}}}"

# Small enough that a crash nothing anticipated costs a minute of fetching.
CHUNK = 100

# Consecutive failures that mean MAL is refusing the key or is down, rather
# than one title being awkward. Stopping says so; skipping 5,000 titles would not.
MAX_CONSECUTIVE_FAILURES = 10

# Where new sequels appear. A finished show is refetched only when something
# new points at it, and then the edge comes from the new title's side.
STILL_CHANGING = frozenset({"current", "upcoming"})

SCHEMA = pa.schema([
    ("mal_id", pa.int64()),
    ("title", pa.string()),
    ("format", pa.string()),
    ("start_date", pa.string()),
    ("poster_url", pa.string()),
    # NULL for a title with no related titles, which is recorded all the same:
    # "fetched, has none" and "never fetched" are different facts, and only the
    # second needs a request.
    ("related_mal_id", pa.int64()),
    ("relation_type", pa.string()),
    ("related_title", pa.string()),
    ("related_format", pa.string()),
    ("related_start_date", pa.string()),
    ("related_poster_url", pa.string()),
    ("fetched_on", pa.string()),
])


def _node(node: dict[str, Any]) -> dict[str, Any]:
    picture = node.get("main_picture") or {}
    return {
        "title": node.get("title"),
        "format": _MEDIA_TYPES.get((node.get("media_type") or "").lower()),
        "start_date": node.get("start_date"),
        "poster_url": picture.get("large") or picture.get("medium"),
    }


def flatten_relations(response: dict[str, Any], run_date: str) -> list[dict[str, Any]]:
    """One row per related title, each carrying both ends; one bare row if none."""
    own = {"mal_id": response["id"], **_node(response), "fetched_on": run_date}
    none = {"related_mal_id": None, "relation_type": None, "related_title": None,
            "related_format": None, "related_start_date": None, "related_poster_url": None}
    edges = response.get("related_anime") or []
    if not edges:
        return [{**own, **none}]
    rows = []
    for edge in edges:
        node = edge.get("node") or {}
        related = _node(node)
        rows.append({
            **own,
            "related_mal_id": node.get("id"),
            "relation_type": edge.get("relation_type"),
            "related_title": related["title"],
            "related_format": related["format"],
            "related_start_date": related["start_date"],
            "related_poster_url": related["poster_url"],
        })
    return rows


def plan(catalogue: list[tuple[int, str | None]], fetched_ever: set[int], fetched_today: set[int]) -> list[int]:
    """Which titles to fetch: never fetched first, then those still changing.

    `catalogue` is (mal_id, status) per title. Anything already fetched today is
    skipped, which is what makes an interrupted run resumable."""
    never = sorted({m for m, _ in catalogue if m not in fetched_ever})
    changing = sorted({
        m for m, status in catalogue
        if m in fetched_ever and m not in fetched_today and status in STILL_CHANGING
    })
    return never + changing


@dataclass
class Fetched:
    titles: int = 0
    edges: int = 0
    gone: list[int] = field(default_factory=list)
    failed: list[int] = field(default_factory=list)


def fetch_relations(
    mal_ids: list[int],
    data_dir: Path,
    run_date: str,
    client: MalClient | None = None,
    chunk: int = CHUNK,
) -> Fetched:
    """Fetch and land related titles for `mal_ids`, one chunk at a time."""
    client = client or MalClient()
    out = Fetched()
    consecutive = 0

    for start in range(0, len(mal_ids), chunk):
        part = mal_ids[start:start + chunk]
        responses: list[dict[str, Any]] = []
        for mal_id in part:
            try:
                responses.append(client.get(f"{MAL_API_URL}/anime/{mal_id}", params={"fields": FIELDS}))
                consecutive = 0
            except requests.HTTPError as exc:
                if exc.response is not None and exc.response.status_code == 404:
                    # Removed from MAL. Recorded as fetched-with-nothing so it is
                    # not asked for again every week.
                    responses.append({"id": mal_id, "related_anime": []})
                    out.gone.append(mal_id)
                    consecutive = 0
                else:
                    out.failed.append(mal_id)
                    consecutive += 1
            except (requests.RequestException, RuntimeError):
                # A timeout, a dropped connection, or retries run out: this title
                # is left for the next run. The first full fetch died on a single
                # 30-second read timeout before this caught it.
                out.failed.append(mal_id)
                consecutive += 1
            if consecutive >= MAX_CONSECUTIVE_FAILURES:
                _land(responses, data_dir, run_date, part[0], out)
                raise RuntimeError(
                    f"{consecutive} MAL requests failed in a row; stopping. "
                    f"{out.titles} titles landed and a rerun resumes after them."
                )
        _land(responses, data_dir, run_date, part[0], out)
        logger.info("Related titles: %s of %s fetched, %s edges", out.titles, len(mal_ids), out.edges)
    return out


def _land(responses: list[dict[str, Any]], data_dir: Path, run_date: str, first_id: int, out: Fetched) -> None:
    """Raw first, then the processed rows derived from it, named by the chunk's
    first title so a resumed run never overwrites an earlier chunk."""
    if not responses:
        return
    name = f"from-{first_id}"
    raw_dir = data_dir / "raw" / "mal_relations" / run_date
    raw_dir.mkdir(parents=True, exist_ok=True)
    (raw_dir / f"{name}.json").write_text(json.dumps(responses, ensure_ascii=False))

    rows = [row for r in responses for row in flatten_relations(r, run_date)]
    processed = data_dir / "processed" / "mal_relations" / run_date
    processed.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pylist(rows, schema=SCHEMA), processed / f"{name}.parquet")

    out.titles += len(responses)
    out.edges += sum(r["related_mal_id"] is not None for r in rows)


def fetch_state(data_dir: Path, run_date: str) -> tuple[list[tuple[int, str | None]], set[int], set[int]]:
    """(mal_id, status) for every catalogue title with a MAL id; the titles ever
    fetched; and those already fetched on `run_date` - what plan() needs."""
    import duckdb

    warehouse = data_dir / "warehouse.duckdb"
    if not warehouse.exists():  # a first run, before any catalogue: nothing to plan
        return [], set(), set()
    con = duckdb.connect(str(warehouse), read_only=True)
    try:
        catalogue = con.execute(
            "SELECT DISTINCT CAST(mal_id AS BIGINT), status FROM anime_media_latest WHERE mal_id IS NOT NULL"
        ).fetchall()
    finally:
        con.close()

    glob = data_dir / "processed" / "mal_relations" / "*" / "*.parquet"
    if not list(glob.parent.parent.glob("*/*.parquet")):
        return catalogue, set(), set()
    rows = duckdb.sql(
        f"SELECT DISTINCT mal_id, fetched_on FROM read_parquet('{glob}')"
    ).fetchall()
    return catalogue, {m for m, _ in rows}, {m for m, d in rows if d == run_date}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--data-dir", type=Path, default=Path("data"))
    parser.add_argument("--run-date", required=True, help="the capture date to stamp, e.g. 2026-09-11")
    parser.add_argument("--limit", type=int, default=None, help="fetch at most this many titles")
    parser.add_argument("--dry-run", action="store_true", help="say what would be fetched, fetch nothing")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    catalogue, ever, today = fetch_state(args.data_dir, args.run_date)
    ids = plan(catalogue, ever, today)[: args.limit]
    never = sum(m not in ever for m in ids)
    print(f"{len(catalogue)} catalogue titles with a MAL id; {len(ever)} fetched before, "
          f"{len(today)} already today. Fetching {len(ids)}: {never} never fetched, "
          f"{len(ids) - never} still airing or upcoming. ~{round(len(ids) * 0.8 / 60)} min.")
    if args.dry_run or not ids:
        return 0

    result = fetch_relations(ids, args.data_dir, args.run_date)
    print(f"landed {result.titles} titles and {result.edges} edges; "
          f"{len(result.gone)} gone from MAL, {len(result.failed)} failed (retried next run)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

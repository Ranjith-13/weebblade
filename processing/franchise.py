"""Franchises: titles joined by MAL's story relations into connected groups.

Built from the relations ingestion/mal/fetch_relations.py lands: each title's
most recent fetch is its current list of related titles. A franchise is a
connected component over the STORY relations - sequel and prequel, side and
parent story, spin-off, summary and full story, alternative version and
setting. Two relation types are left out on purpose:

  character  a character appearing elsewhere. Crossovers and cameo specials
             would chain unrelated franchises into one.
  other      MAL's catch-all: music videos, commercials, collaborations. The
             same problem, worse.

Members include titles older than the catalogue - the prequel from 2019 a
current sequel points at. They are what a franchise page most needs to show,
and MAL's relation entries carry their title, format and date, so they cost
nothing to include.

A franchise is named `fr_{lowest MAL id in it}`: deterministic, usually the
franchise's first entry, and unchanged when a sequel joins. Two franchises
joined by a new link keep the older name.

The output is one table, rebuilt whole each time. It is derived entirely from
the stored relations, so there is nothing in it worth keeping history of.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq

# Which relations join a franchise is defined beside the fetch, which follows
# exactly these outward past the catalogue; the two must never disagree.
from ingestion.mal.fetch_relations import STORY_RELATIONS

logger = logging.getLogger(__name__)


MEMBERS_RELPATH = Path("processed") / "franchise" / "members.parquet"

_SCHEMA = pa.schema([
    ("franchise_id", pa.string()),
    ("mal_id", pa.int64()),
    ("title", pa.string()),
    ("format", pa.string()),
    ("start_date", pa.string()),
    ("poster_url", pa.string()),
    ("size", pa.int64()),
])


def latest_relations(data_dir: Path) -> list[dict]:
    """Every row of each title's most recent fetch, edges and bare rows alike."""
    glob = data_dir / "processed" / "mal_relations" / "*" / "*.parquet"
    if not list((data_dir / "processed" / "mal_relations").glob("*/*.parquet")):
        return []
    return duckdb.sql(f"""
        SELECT * EXCLUDE (_latest) FROM (
            SELECT *, MAX(fetched_on) OVER (PARTITION BY mal_id) AS _latest
            FROM read_parquet('{glob}', union_by_name=true)
        ) WHERE fetched_on = _latest
    """).fetch_arrow_table().to_pylist()


class _Components:
    """Union-find over MAL ids. The smallest id in a set is its root, so the root
    is the franchise's name and needs no second pass to find."""

    def __init__(self) -> None:
        self.parent: dict[int, int] = {}

    def find(self, x: int) -> int:
        self.parent.setdefault(x, x)
        root = x
        while self.parent[root] != root:
            root = self.parent[root]
        while self.parent[x] != root:  # compress the path walked
            self.parent[x], x = root, self.parent[x]
        return root

    def union(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            lo, hi = min(ra, rb), max(ra, rb)
            self.parent[hi] = lo


def franchises(rows: list[dict]) -> list[dict]:
    """Members of every franchise with two or more titles.

    A title's own details come from its own fetch where there is one; a title
    only ever seen as someone else's relation takes them from that entry."""
    nodes: dict[int, dict] = {}
    groups = _Components()

    for row in rows:
        own = row["mal_id"]
        nodes[own] = {k: row[k] for k in ("title", "format", "start_date", "poster_url")}
        groups.find(own)
    for row in rows:
        other = row["related_mal_id"]
        if other is None:
            continue
        nodes.setdefault(other, {
            "title": row["related_title"],
            "format": row["related_format"],
            "start_date": row["related_start_date"],
            "poster_url": row["related_poster_url"],
        })
        if row["relation_type"] in STORY_RELATIONS:
            groups.union(row["mal_id"], other)

    members: dict[int, list[int]] = {}
    for mal_id in nodes:
        members.setdefault(groups.find(mal_id), []).append(mal_id)

    out = []
    for root, ids in members.items():
        if len(ids) < 2:
            continue
        for mal_id in sorted(ids):
            out.append({"franchise_id": f"fr_{root}", "mal_id": mal_id, **nodes[mal_id], "size": len(ids)})
    return out


def build_franchises(data_dir: Path) -> Path | None:
    """Rebuild the franchise table from the stored relations. None if there are none yet."""
    rows = latest_relations(data_dir)
    if not rows:
        logger.warning("No related titles fetched yet - no franchises to build")
        return None
    members = franchises(rows)
    path = data_dir / MEMBERS_RELPATH
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    pq.write_table(pa.Table.from_pylist(members, schema=_SCHEMA), tmp)
    os.replace(tmp, path)  # readers never see a half-written table

    count = len({m["franchise_id"] for m in members})
    largest = max((m["size"] for m in members), default=0)
    logger.info("Built %s franchises over %s titles; the largest has %s", count, len(members), largest)
    return path


if __name__ == "__main__":
    import argparse

    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path, default=Path("data"))
    args = parser.parse_args()
    print(f"Wrote: {build_franchises(args.data_dir)}")

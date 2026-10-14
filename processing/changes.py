"""What changed about each title from one fetch to the next, as its sources report it.

The weekly run refetches the current season from every source, and each fetch
is kept as a dated snapshot per season (processed/{source}_media/{partition}/
{run_date}.parquet). Comparing a source's snapshot with its previous one says
what that source now says differently: a show finished, got an episode count,
a premiere date, a trailer, a streaming link, a new score; or was newly listed.


WHY THE SOURCES' SNAPSHOTS AND NOT THE CATALOGUE'S

The catalogue changes whenever the pipeline does. Between the 13 and 14
September 2026 snapshots AniList joined, three matching rules changed and 59
titles merged: a diff of the catalogue would have reported banner art "added"
to 529 titles and scores "changed" wherever a new source filled a gap. None of
that happened to any show. A source's own snapshots change only when the source
does, and every change keeps the name of the source that reported it.

The same guard runs one level down. Pipeline changes also reach the sources'
snapshots when a fetch starts asking for a field: every row goes from nothing
to something at once. So a field an older snapshot does not have at all is not
compared, and a pair where most rows gain a value for a field at once is taken
as the pipeline filling it, not as news (see _FILLED). A value changing to
another value is always recorded - a season's shows finishing in the same week
is real.


WHAT COUNTS

Only what a person following a show would call news, and what stays still
otherwise. Measured over every pair of consecutive snapshots on 2026-09-14:
member counts and ranks moved for most titles in every pair, and poster URLs
churn with the CDN, so neither is recorded. A score change is recorded only
when it would show on the page, which prints it out of 10 to one decimal.

`listed` is an entry the source created since it was last fetched: an id higher
than any it had listed before, since every source numbers its entries in the
order it creates them. Not merely an id not seen before - a fetch that starts
reaching more of a listing turns up old entries too. Kitsu's paging missed a
block of every season until 2026-09-11, and the refetch that fixed it served
112 entries for the first time. Two had ids above any listed before, both music
videos created that week; the other 110 were older than entries already listed. Over every snapshot to
2026-09-14, "not seen before" would have listed 128 entries, and this lists 26.
"""

from __future__ import annotations

import logging
import os
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import pyarrow as pa
import pyarrow.parquet as pq

from ingestion.streaming import service_name

from . import identity

logger = logging.getLogger(__name__)

SOURCES = ("kitsu", "mal", "anilist")

SCHEMA = pa.schema([
    ("wb_id", pa.string()),
    ("source", pa.string()),
    ("source_id", pa.string()),
    ("field", pa.string()),
    ("old", pa.string()),
    ("new", pa.string()),
    # A name for `new` where the value is not one: a streaming link's service,
    # named as the catalogue names it. Here rather than in the API, whose image
    # does not carry ingestion/.
    ("label", pa.string()),
    # The snapshot the change was seen in, and the one it was compared with.
    ("run_date", pa.string()),
    ("since", pa.string()),
    ("partition", pa.string()),
])


def _score(row: dict[str, Any]) -> str | None:
    """As the page prints it: out of 10, one decimal.

    Every source stores out of 100. Jikan stored out of 10 and was scaled here
    and in normalize.py; it was discontinued on 1 October 2026 and the special
    case went with it."""
    value = row.get("average_score")
    if value is None:
        return None
    return f"{value / 10:.1f}"


def _premiere(row: dict[str, Any]) -> str | None:
    """As precise as the source has it: 2026, 2026-10 or 2026-10-04."""
    year, month, day = row.get("start_year"), row.get("start_month"), row.get("start_day")
    if year is None:
        return None
    if month is None:
        return str(year)
    return f"{year}-{month:02d}" if day is None else f"{year}-{month:02d}-{day:02d}"


def _joined(*columns: str) -> Callable[[dict[str, Any]], str | None]:
    def value(row: dict[str, Any]) -> str | None:
        parts = [row.get(c) for c in columns]
        return None if parts[0] is None else " ".join(str(p) for p in parts if p is not None)
    return value


def _plain(column: str) -> Callable[[dict[str, Any]], str | None]:
    def value(row: dict[str, Any]) -> str | None:
        v = row.get(column)
        return None if v is None else str(v)
    return value


# field -> (the columns it needs in both snapshots, how to read it)
TRACKED: dict[str, tuple[tuple[str, ...], Callable[[dict[str, Any]], str | None]]] = {
    "status": (("status",), _plain("status")),
    "episodes": (("episodes",), _plain("episodes")),
    "score": (("average_score",), _score),
    "premiere": (("start_year", "start_month", "start_day"), _premiere),
    "season": (("season", "season_year"), _joined("season", "season_year")),
    "broadcast": (("broadcast_day", "broadcast_time"), _joined("broadcast_day", "broadcast_time")),
    "trailer": (("trailer_id",), _plain("trailer_id")),
}

# A pair where more than this share of the rows both snapshots hold gain a
# value for a field at once is the pipeline starting to fill it. At least
# _FILLED_MIN rows, so a small listing's two real announcements are not it.
_FILLED = 0.5
_FILLED_MIN = 10


def _id(source_id: str) -> int:
    """A source's entry number; -1 for one that is not a number, which can then
    never read as newer than the rest."""
    return int(source_id) if source_id.isdigit() else -1


@dataclass
class Snapshot:
    source: str
    partition: str
    run_date: str
    columns: set[str]
    rows: dict[str, dict[str, Any]]  # by source_id


def _read(path: Path, source: str) -> Snapshot:
    table = pq.read_table(path)
    rows = {}
    for row in table.to_pylist():
        row["source"] = source
        rows[str(row["source_id"])] = row
    return Snapshot(source, path.parent.name, path.stem, set(table.schema.names), rows)


def snapshots(data_dir: Path, source: str) -> list[Snapshot]:
    """Every snapshot a source has, oldest first."""
    root = data_dir / "processed" / f"{source}_media"
    paths = sorted(root.glob("*/*.parquet"), key=lambda p: (p.stem, p.parent.name)) if root.exists() else []
    return [_read(p, source) for p in paths]


@dataclass
class Report:
    compared: int = 0
    changes: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    filled: list[str] = field(default_factory=list)

    def __str__(self) -> str:
        made = ", ".join(f"{n} {f}" for f, n in sorted(self.changes.items())) or "none"
        skipped = f"; taken as the pipeline filling a field: {', '.join(self.filled)}" if self.filled else ""
        return f"{self.compared} snapshot(s) compared, changes: {made}{skipped}"


def changes_in(history: list[Snapshot], current: Snapshot, report: Report) -> list[dict[str, Any]]:
    """What `current` says differently from what its source said before it.

    `history` is every earlier snapshot of the same source, oldest first. A row
    is compared with the newest earlier snapshot that holds it: the same
    season's if there is one, else another season's, which makes a season move
    a `season` change.
    """
    earlier = [s for s in history if s.run_date < current.run_date]
    same_season = [s for s in earlier if s.partition == current.partition]
    newest_id = max((_id(sid) for s in earlier for sid in s.rows), default=None)

    def prior(source_id: str) -> Snapshot | None:
        for pool in (same_season, earlier):
            for s in reversed(pool):
                if source_id in s.rows:
                    return s
        return None

    found: list[dict[str, Any]] = []
    # (field, prior snapshot) -> [changes], held back until the fill check has run
    pending: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    compared: dict[tuple[str, str, str], int] = defaultdict(int)

    def change(source_id: str, name: str, old: str | None, new: str | None, since: str | None) -> dict[str, Any]:
        return {"wb_id": None, "source": current.source, "source_id": source_id, "field": name,
                "old": old, "new": new, "label": service_name(new) if name == "streaming" else None,
                "run_date": current.run_date, "since": since, "partition": current.partition}

    for source_id, row in current.rows.items():
        before = prior(source_id)
        if before is None:
            if newest_id is not None and _id(source_id) > newest_id:
                found.append(change(source_id, "listed", None, None, earlier[-1].run_date))
            continue

        old_row = before.rows[source_id]
        for name, (columns, read) in TRACKED.items():
            if not all(c in before.columns and c in current.columns for c in columns):
                continue
            key = (name, before.partition, before.run_date)
            compared[key] += 1
            old, new = read(old_row), read(row)
            if new is None or new == old:
                continue
            if old is None:
                pending[key].append(change(source_id, name, old, new, before.run_date))
            else:
                found.append(change(source_id, name, old, new, before.run_date))

        old_urls = set(old_row.get("streaming_urls") or [])
        if "streaming_urls" in before.columns and "streaming_urls" in current.columns:
            key = ("streaming", before.partition, before.run_date)
            compared[key] += 1
            added = sorted(set(row.get("streaming_urls") or []) - old_urls)
            bucket = pending[key] if not old_urls else found
            bucket.extend(change(source_id, "streaming", None, url, before.run_date) for url in added)

    for key, held in pending.items():
        gained = len({c["source_id"] for c in held})
        if gained >= _FILLED_MIN and gained > _FILLED * compared[key]:
            report.filled.append(f"{current.source} {current.partition} {key[0]} "
                                 f"({gained} of {compared[key]} since {key[2]})")
            continue
        found.extend(held)

    for c in found:
        report.changes[c["field"]] += 1
    report.compared += 1
    return found


def _place(found: list[dict[str, Any]], registry: identity.Registry) -> None:
    for c in found:
        c["wb_id"] = registry.identity_of(identity.source_key(c["source"], c["source_id"]))


def _write(data_dir: Path, run_date: str, found: list[dict[str, Any]]) -> Path:
    """processed/changes/{run_date}.parquet, replaced whole, so a retried run
    rewrites its own file rather than adding a second. Written even when empty:
    a week with nothing new is still a week that was checked."""
    out = data_dir / "processed" / "changes" / f"{run_date}.parquet"
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".parquet.tmp")
    found = sorted(found, key=lambda c: (c["source"], c["partition"], c["field"], c["source_id"], c["new"] or ""))
    pq.write_table(pa.Table.from_pylist(found, schema=SCHEMA), tmp)
    os.replace(tmp, out)
    return out


def record_changes(data_dir: Path, run_date: str) -> Report:
    """Compare every snapshot dated `run_date` with what its source said before,
    and write what changed. The weekly DAG runs this after consolidating, when
    the registry holds any title first seen this run."""
    registry, report, found = identity.load(data_dir), Report(), []
    for source in SOURCES:
        history = snapshots(data_dir, source)
        for current in (s for s in history if s.run_date == run_date):
            found += changes_in(history, current, report)
    _place(found, registry)
    _write(data_dir, run_date, found)
    logger.info("Changes for %s: %s", run_date, report)
    return report


def record_history(data_dir: Path) -> Report:
    """record_changes for every date any source has a snapshot, oldest first -
    the log from before this existed. Each date's file is rewritten."""
    registry, report = identity.load(data_dir), Report()
    by_date: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for source in SOURCES:
        history = snapshots(data_dir, source)
        for current in history:
            by_date[current.run_date] += changes_in(history, current, report)
    for run_date, found in sorted(by_date.items()):
        _place(found, registry)
        _write(data_dir, run_date, found)
    logger.info("Change history: %s", report)
    return report


if __name__ == "__main__":
    import argparse

    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path, default=Path("data"))
    parser.add_argument("--run-date", help="One run's snapshots; omit to rebuild the whole history")
    args = parser.parse_args()
    print(record_changes(args.data_dir, args.run_date) if args.run_date else record_history(args.data_dir))

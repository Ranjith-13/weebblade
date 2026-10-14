"""What a run checks about its own output before it calls itself done.

Every task after the fetches runs whatever happened upstream (trigger rule
ALL_DONE). That is what keeps a week with a source down publishing, and it is
also how a run goes green with a task in the middle failed: Airflow takes a
run's state from its last tasks, so record_changes failing on a Sunday would
leave a green run over a week with no changes recorded. Until 2026-09-14 the
only check was someone looking - by hand, or by a one-off scheduled check.

So each DAG ends in check_run, which reads what the run produced, compares it
with the run before, writes the numbers down (processed/runs/{dag}/
{run_date}.json, served at GET /runs) and fails the run when something is
wrong. It reads the run's OUTPUT, not the tasks' reports of themselves: a task
can log "reused 6136" and still have written a catalogue that lost a title,
and it is the catalogue that gets served.


WHAT FAILS A WEEKLY RUN

- A source that landed rows in its previous fetch and none now, or under half
  as many. Nothing is compared for a source with no fetch on record - Jikan
  never answered once before its API was discontinued, and saying so every week
  was not news. The rule outlives it: a source added tomorrow is not a
  regression on the day it is added.
- No complete catalogue snapshot for the run, or a warehouse serving an older
  one than it.
- A title from the previous catalogue gone: neither in this one nor merged into
  a title that is. Consolidation carries every source's past snapshots forward,
  so a title never simply drops out.
- A title split: its source rows now on more than one title.
- More than MERGED_LIMIT merges in one run. The most so far was 59, on
  2026-09-14, when AniList joined and three matching rules changed - by hand,
  not in a scheduled run.
- A task that failed, other than a fetch: the rules above judge a fetch by what
  it landed.


WHAT FAILS A DAILY RUN

A schedule or status fetch that landed nothing where the day before landed
something, a served file older than the run, or a failed task. Answers the
catalogue could not place on a title are counted, not failed: AniList's record
can name a title the catalogue does not hold.
"""

from __future__ import annotations

import json
import logging
import os
import urllib.request
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq

from . import identity

logger = logging.getLogger(__name__)

WEEKLY = "anime_seasonal_pipeline"
DAILY = "anilist_airing"
SOURCES = ("anilist", "kitsu", "mal")

MERGED_LIMIT = 25


@dataclass
class Finding:
    level: str  # "fail", or "note" for what is worth reading but not wrong
    message: str


@dataclass
class RunRecord:
    dag: str
    run_date: str
    numbers: dict[str, Any] = field(default_factory=dict)
    findings: list[Finding] = field(default_factory=list)
    failed_tasks: list[str] = field(default_factory=list)
    checked_at: str = ""

    @property
    def passed(self) -> bool:
        return not any(f.level == "fail" for f in self.findings)

    def fail(self, message: str) -> None:
        self.findings.append(Finding("fail", message))

    def note(self, message: str) -> None:
        self.findings.append(Finding("note", message))

    def summary(self) -> str:
        head = f"{self.dag} {self.run_date}: {'passed' if self.passed else 'FAILED'}"
        return "\n".join([head] + [f"{f.level}: {f.message}" for f in self.findings])


def _rows(path: Path) -> int:
    return pq.ParquetFile(path).metadata.num_rows


def _landed(data_dir: Path, source: str, run_date: str) -> dict[str, Any]:
    """Rows a source landed on run_date, and in its previous fetch of each of
    the same seasons. A source that landed nothing is compared with its newest
    fetch of anything - whether it had been answering at all."""
    root = data_dir / "processed" / f"{source}_media"
    now = list(root.glob(f"*/{run_date}.parquet"))
    out: dict[str, Any] = {"rows": sum(_rows(p) for p in now), "previous": None, "previous_date": None}
    if now:
        before = []
        for p in now:
            earlier = sorted(q for q in p.parent.glob("*.parquet") if q.stem < run_date)
            if earlier:
                before.append(earlier[-1])
        if before:
            out.update(previous=sum(_rows(p) for p in before), previous_date=max(p.stem for p in before))
    else:
        dates = sorted({p.stem for p in root.glob("*/*.parquet") if p.stem < run_date})
        if dates:
            out.update(previous=sum(_rows(p) for p in root.glob(f"*/{dates[-1]}.parquet")), previous_date=dates[-1])
    return out


def _titles(snapshot: Path) -> dict[str, list[str]]:
    """wb_id -> source keys, for a catalogue snapshot."""
    table = pq.read_table(snapshot, columns=["wb_id", "source_keys"])
    return {r["wb_id"]: list(r["source_keys"] or []) for r in table.to_pylist() if r["wb_id"]}


def _complete(data_dir: Path) -> list[Path]:
    root = data_dir / "processed" / "anime_media_consolidated" / "_catalogue"
    return sorted(d for d in root.glob("*") if (d / "_SUCCESS").exists() and any(d.glob("*.parquet")))


def _identities(before: dict[str, list[str]], now: dict[str, list[str]], registry: identity.Registry) -> dict[str, Any]:
    """How the previous catalogue's titles fared in this one."""
    kept, merged, lost, split = [], [], [], []
    for wb_id, keys in before.items():
        homes = {h for h in (registry.identity_of(k) for k in keys) if h in now}
        if wb_id in now:
            kept.append(wb_id)
        elif registry.resolve(wb_id) in now:
            merged.append(wb_id)
        else:
            lost.append(wb_id)
        if len(homes) > 1:
            split.append(f"{wb_id} -> {', '.join(sorted(homes))}")
    return {"kept": len(kept), "minted": len(set(now) - set(before)), "merged": len(merged),
            "lost": lost, "split": split}


def _query(db_path: Path, sql: str) -> list[tuple] | None:
    """A read-only question for the warehouse; None when it cannot answer -
    no file yet, or no such view."""
    if not db_path.exists():
        return None
    import duckdb

    con = duckdb.connect(str(db_path), read_only=True)
    try:
        return con.execute(sql).fetchall()
    except duckdb.CatalogException:
        return None
    finally:
        con.close()


def _served(db_path: Path) -> str | None:
    """The run date of the catalogue the warehouse serves - asked of the view
    itself, which a failed refresh leaves on the old snapshot."""
    rows = _query(db_path, "SELECT MAX(run_date) FROM anime_media_latest")
    return rows[0][0] if rows else None


def check_weekly(data_dir: Path, run_date: str, failed_tasks: list[str] | None = None,
                 db_path: Path | None = None) -> RunRecord:
    record = RunRecord(WEEKLY, run_date, failed_tasks=sorted(failed_tasks or []))

    sources = {s: _landed(data_dir, s, run_date) for s in SOURCES}
    record.numbers["sources"] = sources
    for s, got in sources.items():
        if not got["previous"]:
            continue
        if got["rows"] == 0:
            record.fail(f"{s} landed nothing; its fetch of {got['previous_date']} landed {got['previous']} rows")
        elif got["rows"] < got["previous"] / 2:
            record.fail(f"{s} landed {got['rows']} rows, under half the {got['previous']} of {got['previous_date']}")

    complete = _complete(data_dir)
    this = next((d for d in complete if d.name == run_date), None)
    served = _served(db_path or data_dir / "warehouse.duckdb")
    record.numbers["served_snapshot"] = served
    if this is None:
        record.fail(f"No complete catalogue snapshot for {run_date}")
    else:
        now = _titles(this)
        record.numbers["titles"] = len(now)
        earlier = [d for d in complete if d.name < run_date]
        if earlier:
            before = _titles(earlier[-1])
            ids = _identities(before, now, identity.load(data_dir))
            record.numbers.update(titles_before=len(before), since=earlier[-1].name,
                                  kept=ids["kept"], minted=ids["minted"], merged=ids["merged"],
                                  lost=len(ids["lost"]), split=len(ids["split"]))
            if ids["lost"]:
                record.fail(f"{len(ids['lost'])} title(s) from {earlier[-1].name} gone: {', '.join(ids['lost'][:5])}")
            if ids["split"]:
                record.fail(f"{len(ids['split'])} title(s) split: {'; '.join(ids['split'][:5])}")
            if ids["merged"] > MERGED_LIMIT:
                record.fail(f"{ids['merged']} titles merged into others, more than {MERGED_LIMIT} in one run")
    if served is None or served < run_date:
        record.fail(f"The warehouse serves the catalogue of {served or 'no date'}, not {run_date}")

    changes = data_dir / "processed" / "changes" / f"{run_date}.parquet"
    if changes.exists():
        by_field: dict[str, int] = {}
        for row in pq.read_table(changes, columns=["field"]).to_pylist():
            by_field[row["field"]] = by_field.get(row["field"], 0) + 1
        record.numbers["changes"] = by_field
    else:
        record.fail(f"No changes recorded for {run_date}")

    record.numbers["digest"] = (data_dir / "digests" / f"{run_date}.md").exists()
    _failed_tasks(record, skip_prefix="fetch_")
    return _save(data_dir, record)


def check_daily(data_dir: Path, run_date: str, failed_tasks: list[str] | None = None,
                db_path: Path | None = None) -> RunRecord:
    record = RunRecord(DAILY, run_date, failed_tasks=sorted(failed_tasks or []))
    processed = data_dir / "processed"
    for name in ("anilist_airing", "anilist_status"):
        dated = sorted((processed / name).glob("*.parquet")) if (processed / name).exists() else []
        today = next((p for p in dated if p.stem == run_date), None)
        before = [p for p in dated if p.stem < run_date]
        rows = _rows(today) if today else 0
        previous = _rows(before[-1]) if before else None
        record.numbers[name] = {"rows": rows, "previous": previous}
        if previous and rows == 0:
            record.fail(f"{name} landed nothing; {before[-1].stem} landed {previous}")
        current = processed / "current" / f"{name}.parquet"
        held = pq.read_table(current, columns=["fetched_on"]).column(0).to_pylist() if current.exists() else []
        served = max((d for d in held if d), default=None)
        # Only once today's fetch landed something: an empty one is the finding above.
        if rows and served != run_date:
            record.fail(f"The served {name} is from {served}, not {run_date}")

    # What the day's title searches turned up, where it ran (see
    # ingestion/anilist/resolve_ids.py). Numbers only: a day that matched
    # nothing is an ordinary day once the backlog is through.
    searched = processed / "anilist_resolved" / f"{run_date}.parquet"
    if searched.exists():
        ids = pq.read_table(searched, columns=["anilist_id"]).column(0)
        record.numbers["anilist_resolved"] = {
            "searched": len(ids), "matched": len(ids) - ids.null_count
        }

    unplaced = _unplaced_answers(db_path or data_dir / "warehouse.duckdb")
    if unplaced:
        record.numbers["unplaced_answers"] = len(unplaced)
        record.note(f"{len(unplaced)} AniList answer(s) on no catalogue title: {', '.join(unplaced[:5])}")
    _failed_tasks(record)
    return _save(data_dir, record)


def _unplaced_answers(db_path: Path) -> list[str]:
    rows = _query(db_path, "SELECT anilist_id, mal_id FROM anime_anilist_status WHERE wb_id IS NULL ORDER BY anilist_id")
    return [f"anilist {a}" + (f" (mal {m})" if m else "") for a, m in rows or []]


def _failed_tasks(record: RunRecord, skip_prefix: str | None = None) -> None:
    judged = [t for t in record.failed_tasks if not (skip_prefix and t.startswith(skip_prefix))]
    if judged:
        record.fail(f"Task(s) failed: {', '.join(judged)}")


def _save(data_dir: Path, record: RunRecord) -> RunRecord:
    record.checked_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    out = data_dir / "processed" / "runs" / record.dag / f"{record.run_date}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".json.tmp")
    body = asdict(record) | {"passed": record.passed}
    tmp.write_text(json.dumps(body, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(tmp, out)
    return record


def notify(record: RunRecord) -> bool:
    """Push a failed run to ntfy, where the server's other alerts go - only when
    NTFY_TOPIC is set. A notification that cannot be sent is logged and never
    hides the failure it was about."""
    topic = os.environ.get("NTFY_TOPIC", "").strip()
    if not topic or record.passed:
        return False
    request = urllib.request.Request(
        f"https://ntfy.sh/{topic}",
        data=record.summary().encode("utf-8"),
        headers={"Title": f"WeebBlade {record.dag} {record.run_date} failed its checks",
                 "Tags": "warning", "User-Agent": "weebblade-run-checks"},
    )
    try:
        with urllib.request.urlopen(request, timeout=10):
            return True
    except OSError:
        logger.warning("Could not send the failed-run notification", exc_info=True)
        return False

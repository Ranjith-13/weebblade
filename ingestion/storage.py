from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq


def write_raw_json(raw_list: list[dict[str, Any]], out_dir: Path, run_date: str) -> Path:
    """Land the unmodified API response as JSON - the bronze/raw layer."""
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{run_date}.json"
    out_path.write_text(json.dumps(raw_list, ensure_ascii=False, indent=2))
    return out_path


def write_parquet(rows: list[dict[str, Any]], out_dir: Path, run_date: str) -> Path:
    """Write already-flattened rows as a dated Parquet snapshot - the queryable layer."""
    out_dir.mkdir(parents=True, exist_ok=True)
    table = pa.Table.from_pylist(rows)
    out_path = out_dir / f"{run_date}.parquet"
    pq.write_table(table, out_path)
    return out_path


def write_daily(
    rows: list[dict[str, Any]], schema: pa.Schema, data_dir: Path, name: str, run_date: str
) -> Path:
    """A daily fetch's rows: the day's dated file, and the one file that is served.

    processed/{name}/{run_date}.parquet keeps every day's answer as history. The
    warehouse reads processed/current/{name}.parquet instead - one file, however
    many days have passed. Reading the dated glob would cost every query a file
    more each day, and AniList's status check is joined into anime_media_latest,
    which every request reads.

    Each is written under a temporary name and moved into place, so a query never
    reads half a file. The current file is only replaced by a day at least as new
    as the one it holds: rerunning an old date must not put yesterday back.
    """
    table = pa.Table.from_pylist(rows, schema=schema)
    dated = data_dir / "processed" / name / f"{run_date}.parquet"
    current = data_dir / "processed" / "current" / f"{name}.parquet"

    targets = [dated]
    held = _held_date(current)
    if held is None or run_date >= held:
        targets.append(current)
    for path in targets:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        pq.write_table(table, tmp)
        tmp.replace(path)
    return current


def _held_date(path: Path) -> str | None:
    """The newest fetched_on in a current file, or None if there is none to keep."""
    if not path.exists():
        return None
    dates = [d for d in pq.read_table(path, columns=["fetched_on"]).column("fetched_on").to_pylist() if d]
    return max(dates) if dates else None

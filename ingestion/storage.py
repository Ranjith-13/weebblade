from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq


def write_raw_json(raw_list: list[dict[str, Any]], out_dir: Path, run_date: str) -> Path:
    """Land the unmodified API response as JSON — the bronze/raw layer."""
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{run_date}.json"
    out_path.write_text(json.dumps(raw_list, ensure_ascii=False, indent=2))
    return out_path


def write_parquet(rows: list[dict[str, Any]], out_dir: Path, run_date: str) -> Path:
    """Write already-flattened rows as a dated Parquet snapshot — the queryable layer."""
    out_dir.mkdir(parents=True, exist_ok=True)
    table = pa.Table.from_pylist(rows)
    out_path = out_dir / f"{run_date}.parquet"
    pq.write_table(table, out_path)
    return out_path

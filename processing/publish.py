"""Turn the warehouse into something that can leave this machine.

refresh_catalog builds views - `SELECT ... FROM read_parquet('/data/...')` - with
the absolute path of every parquet file baked in at CREATE VIEW time. That is
right where it runs, and useless anywhere else: moved, the views resolve to
nothing and the warehouse answers every query with no rows rather than an error,
which is the worst way for it to fail. scripts/weebblade-backup.sh warns about
exactly this for restores.

So materialising is not an optimisation, it is what makes the file an artifact.
Every view becomes a table holding its rows, and the result depends on nothing
outside itself: a reader can download it, open it, and serve the catalogue with
no lake, no object store and no credentials.

It is faster too, measured over the live catalogue on 2026-10-11:

    catalogue summary   20.1 ms -> 1.7 ms
    one season page     47.8 ms -> 6.6 ms
    one title           53.6 ms -> 4.1 ms
    schedule join       23.1 ms -> 2.0 ms

for 27.5 MB, plus about 10 MB once the vectors are in it - a single file holding
the whole serving layer, built in about a second.
"""

from __future__ import annotations

import logging
from pathlib import Path

import duckdb

logger = logging.getLogger(__name__)


def materialise(warehouse: Path, out_path: Path) -> Path | None:
    """Write a self-contained copy of `warehouse` to `out_path`.

    Every view becomes a table; tables already in there (the mapped MAL ids, the
    vectors) are copied as they are, types included - the vector column has to
    stay a fixed-size ARRAY or array_cosine_similarity will not take it.

    Returns None when there is nothing to copy, which is the state before the
    first successful run rather than an error.
    """
    if not warehouse.exists():
        logger.warning("No warehouse at %s to publish", warehouse)
        return None

    out_path.unlink(missing_ok=True)
    source = duckdb.connect(str(warehouse), read_only=True)
    try:
        names = [
            row[0] for row in source.execute(
                "SELECT table_name FROM information_schema.tables WHERE table_schema = 'main'"
            ).fetchall()
        ]
    finally:
        source.close()

    if not names:
        logger.warning("Warehouse at %s holds nothing yet", warehouse)
        return None

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out = duckdb.connect(str(out_path))
    try:
        out.execute(f"ATTACH '{warehouse}' AS src (READ_ONLY)")
        for name in names:
            out.execute(f"CREATE TABLE {name} AS SELECT * FROM src.{name}")
        out.execute("DETACH src")
    finally:
        out.close()

    logger.info(
        "Materialised %s object(s) into %s (%.1f MB)",
        len(names), out_path.name, out_path.stat().st_size / 1e6,
    )
    return out_path

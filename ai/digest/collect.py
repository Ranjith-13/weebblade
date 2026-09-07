from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import duckdb

from .queries import STATS_QUERIES

logger = logging.getLogger(__name__)

_EMPTY_STATS: dict[str, list[dict[str, Any]]] = {name: [] for name in STATS_QUERIES}


def collect_stats(db_path: Path) -> dict[str, list[dict[str, Any]]]:
    """Run each stats query against the warehouse and return rows as plain dicts.

    Uses pyarrow's to_pylist() rather than pulling in pandas just for this - pyarrow
    is already a dependency of the ingestion layer.

    Returns all-empty stats (rather than raising) if the warehouse file or the
    anime_media_latest view don't exist yet - a legitimate state whenever every
    source has failed on a given run, not just before the very first successful one.
    """
    if not db_path.exists():
        logger.warning("Warehouse file %s doesn't exist yet", db_path)
        return _EMPTY_STATS

    con = duckdb.connect(str(db_path), read_only=True)
    try:
        return {
            name: con.execute(sql).fetch_arrow_table().to_pylist()
            for name, sql in STATS_QUERIES.items()
        }
    except duckdb.CatalogException:
        logger.warning("anime_media_latest view doesn't exist yet in %s", db_path)
        return _EMPTY_STATS
    finally:
        con.close()

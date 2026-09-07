from __future__ import annotations

import logging
from pathlib import Path

import duckdb

logger = logging.getLogger(__name__)

# Each view is a glob over that source's dated Parquet snapshots. Anything that opens
# the resulting DuckDB file (the backend, a notebook, the future digest script) just
# queries these as normal tables without needing to know the on-disk layout.
_VIEWS = {
    "anime_media": "processed/anime_media_consolidated/*/*/*.parquet",
    "anime_media_anilist": "processed/anilist_media/*/*.parquet",
    "anime_media_jikan": "processed/jikan_media/*/*.parquet",
    "anime_media_kitsu": "processed/kitsu_media/*/*.parquet",
}


def refresh_catalog(data_dir: Path, db_path: Path) -> list[str]:
    """(Re)create views over the Parquet lake. Returns the view names that were
    actually (re)created - a source/partition with no files yet is skipped with a
    warning rather than failing the whole refresh, since this runs even when some
    upstream sources are down.
    """
    con = duckdb.connect(str(db_path))
    created = []
    try:
        for view_name, glob_suffix in _VIEWS.items():
            glob_path = str(data_dir / glob_suffix)
            try:
                con.execute(
                    f"CREATE OR REPLACE VIEW {view_name} AS "
                    f"SELECT * FROM read_parquet('{glob_path}', union_by_name=true)"
                )
                created.append(view_name)
                logger.info("Refreshed view %s -> %s", view_name, glob_path)
            except duckdb.IOException:
                logger.warning("No files yet for view %s (%s), skipping", view_name, glob_path)
    finally:
        con.close()
    return created


if __name__ == "__main__":
    import argparse

    logging.basicConfig(level=logging.INFO)

    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path, default=Path("data"))
    parser.add_argument("--db-path", type=Path, default=None)
    args = parser.parse_args()

    db_path = args.db_path or args.data_dir / "warehouse.duckdb"
    views = refresh_catalog(args.data_dir, db_path)
    print(f"Refreshed {len(views)} view(s) at {db_path}: {views}")

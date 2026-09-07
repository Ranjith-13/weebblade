from __future__ import annotations

import logging
from pathlib import Path

from pyspark.sql import DataFrame
from pyspark.sql import functions as F

from .normalize import standardize_schema
from .spark import get_spark_session

logger = logging.getLogger(__name__)

SOURCE_DIR_NAMES = {"anilist": "anilist_media", "jikan": "jikan_media", "kitsu": "kitsu_media"}


def consolidate_partition(data_dir: Path, partition: str, run_date: str) -> Path | None:
    """Union whichever sources actually produced a snapshot for this partition/run_date.

    Sources that failed to fetch (or haven't run at all) are skipped with a warning,
    not treated as a hard error - this is meant to run even when some upstream
    sources are down, which is the normal case right now (see PROGRESS.md).
    """
    spark = get_spark_session("weebblade-consolidate")
    frames: list[DataFrame] = []

    for source, dir_name in SOURCE_DIR_NAMES.items():
        path = data_dir / "processed" / dir_name / partition / f"{run_date}.parquet"
        if not path.exists():
            logger.warning("No snapshot for %s at %s, skipping", source, path)
            continue
        df = standardize_schema(spark.read.parquet(str(path)))
        logger.info("Loaded %s rows from %s", df.count(), source)
        frames.append(df)

    if not frames:
        logger.warning(
            "No source data available for partition %s / %s - nothing to consolidate",
            partition,
            run_date,
        )
        spark.stop()
        return None

    consolidated = frames[0]
    for df in frames[1:]:
        consolidated = consolidated.unionByName(df)

    # run_date as a real column, not just a path component - lets the DuckDB catalog
    # pick the latest snapshot per title once multiple weekly runs have landed (see
    # duckdb_catalog.anime_media_latest), and supports trend-over-time queries later.
    consolidated = consolidated.withColumn("run_date", F.lit(run_date))

    out_dir = data_dir / "processed" / "anime_media_consolidated" / partition / run_date
    consolidated.coalesce(1).write.mode("overwrite").parquet(str(out_dir))
    logger.info("Wrote consolidated output to %s", out_dir)

    spark.stop()
    return out_dir


if __name__ == "__main__":
    import argparse

    logging.basicConfig(level=logging.INFO)

    parser = argparse.ArgumentParser()
    parser.add_argument("partition", help="e.g. 2026-SUMMER")
    parser.add_argument("run_date", help="e.g. 2026-09-07")
    parser.add_argument("--data-dir", type=Path, default=Path("data"))
    args = parser.parse_args()

    result = consolidate_partition(args.data_dir, args.partition, args.run_date)
    print(f"Wrote: {result}" if result else "Nothing to consolidate")

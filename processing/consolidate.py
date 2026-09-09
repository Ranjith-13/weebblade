from __future__ import annotations

import logging
from pathlib import Path

from pyspark.sql import DataFrame, Window
from pyspark.sql import functions as F

from .normalize import standardize_schema
from .spark import get_spark_session

logger = logging.getLogger(__name__)

SOURCE_DIR_NAMES = {
    "anilist": "anilist_media",
    "jikan": "jikan_media",
    "mal": "mal_media",
    "kitsu": "kitsu_media",
}

# Which source wins when two of them describe the same show. Lower is preferred.
#
# Kitsu leads not because it is richer but because it is the source that has been
# live throughout: every stored row already uses its vocabulary for `format` and
# `status`, and it is the only source carrying streaming links, trailers and
# cover art. MAL then fills the gaps Kitsu cannot - studios and source_material
# are null for 100% of Kitsu rows - and supplies scores for titles Kitsu has
# never rated.
#
# This is a field-level merge, not a row-level pick: for every column the first
# non-null value in this order wins, so a title takes its streaming links from
# Kitsu and its studios from MAL in the same row.
_SOURCE_PRIORITY = ["kitsu", "anilist", "mal", "jikan"]


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

    consolidated = _merge_sources(consolidated)

    # run_date as a real column, not just a path component - lets the DuckDB catalog
    # pick the latest snapshot per title once multiple weekly runs have landed (see
    # duckdb_catalog.anime_media_latest), and supports trend-over-time queries later.
    consolidated = consolidated.withColumn("run_date", F.lit(run_date))

    out_dir = data_dir / "processed" / "anime_media_consolidated" / partition / run_date
    consolidated.coalesce(1).write.mode("overwrite").parquet(str(out_dir))
    logger.info("Wrote consolidated output to %s", out_dir)

    spark.stop()
    return out_dir


def _merge_sources(df: DataFrame) -> DataFrame:
    """Collapse rows from different sources that describe the same show.

    Without this, adding a second live source doubles the catalogue: Kitsu and
    MAL both carry BLEACH under different ids, and a plain union keeps both, so
    every popular title appears twice in the UI.

    Rows are matched on `mal_id`, which Kitsu supplies via its mappings
    relationship. A row with no mal_id cannot be matched to anything and keeps
    its own identity, which is the safe default: a false merge silently deletes a
    title, while a missed merge merely leaves a duplicate that is visible and
    fixable.

    The merge is per-column, taking the first non-null value in source-priority
    order, so one output row can hold Kitsu's streaming links and MAL's studios
    at once. `source` and `source_id` are taken from the winning source so the
    row still points at a real upstream record.
    """
    priority = F.create_map(
        *[x for i, s in enumerate(_SOURCE_PRIORITY) for x in (F.lit(s), F.lit(i))]
    )
    df = df.withColumn(
        "_priority", F.coalesce(priority[F.col("source")], F.lit(len(_SOURCE_PRIORITY)))
    ).withColumn(
        # Rows without a mal_id are unmatchable, so they group only with
        # themselves. Prefixing keeps a mal_id of 5 from colliding with a
        # source_id of "5".
        "_key",
        F.when(F.col("mal_id").isNotNull(), F.concat(F.lit("mal:"), F.col("mal_id")))
        .otherwise(F.concat(F.lit("src:"), F.col("source"), F.lit(":"), F.col("source_id"))),
    )

    # An ORDERED window, not groupBy(...).agg(first(...)): inside a groupBy,
    # `first` has no defined order, so which source won would vary between runs.
    # The frame must span the whole partition or `first` only sees rows up to the
    # current one.
    window = (
        Window.partitionBy("_key")
        .orderBy("_priority")
        .rowsBetween(Window.unboundedPreceding, Window.unboundedFollowing)
    )
    columns = [c for c in df.columns if c not in ("_key", "_priority")]
    merged = df.select(
        F.col("_key"),
        *[F.first(F.col(c), ignorenulls=True).over(window).alias(c) for c in columns],
    )
    return merged.dropDuplicates(["_key"]).drop("_key")


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

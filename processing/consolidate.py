from __future__ import annotations

import logging
from pathlib import Path

from pyspark.sql import DataFrame, Window
from pyspark.sql import functions as F
from pyspark.sql.types import ArrayType

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


def _snapshot_for(source_dir: Path, run_date: str) -> Path | None:
    """The snapshot to consolidate for one source: this run's if it exists, else
    the most recent earlier one.

    The fallback is the whole point. Sources are not fetched on the same day -
    Kitsu's Spring 2026 snapshot is dated 2026-06-15 and MAL's is 2026-09-09 -
    and an exact-date lookup silently dropped every source that had not been
    re-fetched today. `_merge_sources` can only merge rows it is handed, so a
    title whose two sources landed in different runs stayed doubled in the
    catalogue permanently: the DuckDB `anime_media_latest` view dedupes by
    (source, source_id), which differs between the two halves, so nothing
    downstream could collapse them either. That produced 12 visible duplicate
    pairs in live data, all of them Kitsu-from-June against MAL-from-September.

    Bounded by `<= run_date` so re-running an old date reproduces what that run
    would have seen, rather than pulling in snapshots from its future.
    """
    exact = source_dir / f"{run_date}.parquet"
    if exact.exists():
        return exact
    if not source_dir.is_dir():
        return None
    earlier = sorted(p for p in source_dir.glob("*.parquet") if p.stem <= run_date)
    return earlier[-1] if earlier else None


def consolidate_partition(data_dir: Path, partition: str, run_date: str) -> Path | None:
    """Union whichever sources have a snapshot for this partition, newest first.

    Sources that failed to fetch (or haven't run at all) are skipped with a warning,
    not treated as a hard error - this is meant to run even when some upstream
    sources are down, which is the normal case right now (see PROGRESS.md).

    A source with no snapshot for *this* run_date is carried forward from its most
    recent earlier one rather than dropped, so the merge always sees every source
    that has ever reported on the season. See `_snapshot_for`.
    """
    spark = get_spark_session("weebblade-consolidate")
    frames: list[DataFrame] = []

    for source, dir_name in SOURCE_DIR_NAMES.items():
        source_dir = data_dir / "processed" / dir_name / partition
        path = _snapshot_for(source_dir, run_date)
        if path is None:
            logger.warning("No snapshot for %s under %s, skipping", source, source_dir)
            continue
        if path.stem != run_date:
            logger.info(
                "No %s snapshot for %s - carrying forward %s so the merge still sees it",
                source,
                run_date,
                path.stem,
            )
        df = standardize_schema(spark.read.parquet(str(path)))
        logger.info("Loaded %s rows from %s (snapshot %s)", df.count(), source, path.stem)
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

    Three passes, because one key is not enough:

    1. `mal_id`, which Kitsu supplies via its mappings relationship. This is the
       reliable key and catches the large majority.
    2. `title_romaji` + format, for the rows pass 1 cannot match. Measured against
       the live Summer 2026 data, 14 Kitsu rows carry no MAL mapping at all, so
       their MAL twins survived pass 1 as visible duplicates. Most of those have
       byte-identical romaji.
    3. display title (`title_english`, falling back to romaji) + format, because
       romaji is a transliteration and the two sources transliterate differently:
       "Otome Kaiju Caramelise" against "Otome Kaijuu Caraméliser", "Magical Girl
       Lyrical Nanoha EXCEEDS" against "Mahou Shoujo Lyrical Nanoha EXCEEDS",
       "Koukaku Kidoutai: THE GHOST IN THE SHELL" against "Koukaku Kidoutai (TV)".
       All five such live pairs agree on the English title. The coalesce matters:
       two of them have no English title on the Kitsu side, and match Kitsu's
       romaji against MAL's English.

    Passes 2 and 3 are deliberately narrow. Each requires an exact (case- and
    whitespace-insensitive) title AND the same format, and consolidate already
    runs per season, so a false merge needs two different shows sharing a title,
    a format and a season. A false merge silently deletes a title, which is worse
    than the duplicate it prevents, so anything less certain than that - fuzzy
    distance, substring, title without format - is left alone.

    The merge is per-column, taking the first non-null value in source-priority
    order, so one output row holds Kitsu's streaming links and MAL's studios at
    once.
    """
    matched_by_id = _merge_on(
        df,
        F.when(F.col("mal_id").isNotNull(), F.concat(F.lit("mal:"), F.col("mal_id"))).otherwise(
            _identity_key()
        ),
    )
    matched_by_romaji = _merge_on(matched_by_id, _title_key("tr:", F.col("title_romaji")))
    return _merge_on(
        matched_by_romaji,
        _title_key("td:", F.coalesce(F.col("title_english"), F.col("title_romaji"))),
    )


def _identity_key() -> "F.Column":
    """A key that matches only the row itself, so an unmatchable row survives a
    pass untouched instead of grouping with every other unmatchable row."""
    return F.concat(F.lit("src:"), F.col("source"), F.lit(":"), F.col("source_id"))


def _title_key(prefix: str, title: "F.Column") -> "F.Column":
    """Case- and whitespace-insensitive title + format, or the row's own identity
    when either part is missing."""
    return F.when(
        title.isNotNull() & F.col("format").isNotNull(),
        F.concat(F.lit(prefix), F.lower(F.trim(title)), F.lit("|"), F.lower(F.col("format"))),
    ).otherwise(_identity_key())


def _merge_on(df: DataFrame, key: "F.Column") -> DataFrame:
    """Group by `key` and take the first non-null value of every column in
    source-priority order.

    An ORDERED window, not groupBy(...).agg(first(...)): inside a groupBy,
    `first` has no defined order, so which source won would vary between runs.
    The frame must span the whole partition or `first` only sees rows up to the
    current one.
    """
    priority = F.create_map(
        *[x for i, s in enumerate(_SOURCE_PRIORITY) for x in (F.lit(s), F.lit(i))]
    )
    df = df.withColumn(
        "_priority", F.coalesce(priority[F.col("source")], F.lit(len(_SOURCE_PRIORITY)))
    ).withColumn("_key", key)

    window = (
        Window.partitionBy("_key")
        .orderBy("_priority")
        .rowsBetween(Window.unboundedPreceding, Window.unboundedFollowing)
    )
    # An EMPTY ARRAY is not a value, it is an absence, and treating it as a value
    # is a real bug this hit: Kitsu emitted studios as [] meaning "no studio data
    # here", ignorenulls accepted it, and because Kitsu outranks MAL every merged
    # row ended up with no studios at all while MAL's populated list sat right
    # there. Sources now emit null instead, and this makes the merge immune
    # regardless of what any future source does.
    fields = {f.name: f.dataType for f in df.schema.fields}

    def meaningful(name: str) -> "F.Column":
        col = F.col(name)
        if isinstance(fields.get(name), ArrayType):
            return F.when(F.size(col) > 0, col)
        return col

    columns = [c for c in df.columns if c not in ("_key", "_priority")]
    merged = df.select(
        F.col("_key"),
        *[F.first(meaningful(c), ignorenulls=True).over(window).alias(c) for c in columns],
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

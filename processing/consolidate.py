from __future__ import annotations

import logging
from pathlib import Path

from pyspark.sql import DataFrame, Window
from pyspark.sql import functions as F
from pyspark.sql.types import ArrayType

from . import identity
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

# Carried through every merge pass as the union of its members, never as a winner.
_SOURCE_KEYS = "source_keys"


def _snapshots_upto(source_dir: Path, run_date: str) -> list[Path]:
    """Every snapshot a source has produced for this partition, oldest first.

    Bounded by `<= run_date` so re-running an old date reproduces what that run
    would have seen, rather than pulling in snapshots from its future.
    """
    if not source_dir.is_dir():
        return []
    return sorted(p for p in source_dir.glob("*.parquet") if p.stem <= run_date)


def _current_state(spark, source_dir: Path, run_date: str) -> DataFrame | None:
    """One source's current view of a season: the latest row per id across all of
    its snapshots, not just the file dated today.

    Reading a single dated file was the bug behind 12 duplicate pairs in live
    data. Sources are not fetched on the same day - Kitsu's Spring 2026 snapshot
    is dated 2026-06-15 and MAL's 2026-09-09 - so an exact-date lookup found no
    Kitsu file and skipped the source outright. `_merge_sources` can only merge
    rows it is handed, and nothing downstream could repair it: the DuckDB
    `anime_media_latest` view dedupes by (source, source_id), which differs
    between the two halves of a title, so both survived forever.

    Taking the newest earlier file instead would still have missed two more
    pairs, where the source WAS fetched today but had dropped the title from its
    listing, leaving its last good row in an older snapshot. Reducing over every
    snapshot covers both, and it is the same rule `anime_media_latest` already
    applies downstream - a title keeps its last-seen row until a source reports a
    newer one. Applying it here just means the merge gets to see that row.
    """
    paths = _snapshots_upto(source_dir, run_date)
    if not paths:
        return None

    df = None
    for path in paths:
        frame = standardize_schema(spark.read.parquet(str(path))).withColumn(
            "_snapshot", F.lit(path.stem)
        )
        df = frame if df is None else df.unionByName(frame)

    newest = Window.partitionBy("source", "source_id").orderBy(F.col("_snapshot").desc())
    return (
        df.withColumn("_rn", F.row_number().over(newest))
        .filter(F.col("_rn") == 1)
        .drop("_rn", "_snapshot")
    )


def consolidate_partition(data_dir: Path, partition: str, run_date: str) -> Path | None:
    """Union whichever sources have a snapshot for this partition, newest first.

    Sources that failed to fetch (or haven't run at all) are skipped with a warning,
    not treated as a hard error - this is meant to run even when some upstream
    sources are down, which is the normal case right now (see PROGRESS.md).

    Each source contributes its CURRENT state for the partition - the latest row
    per id across all of its snapshots - rather than only the file dated today, so
    the merge always sees every source that has ever reported on the season. See
    `_current_state`.
    """
    spark = get_spark_session("weebblade-consolidate")
    frames: list[DataFrame] = []

    for source, dir_name in SOURCE_DIR_NAMES.items():
        source_dir = data_dir / "processed" / dir_name / partition
        snapshots = _snapshots_upto(source_dir, run_date)
        df = _current_state(spark, source_dir, run_date)
        if df is None:
            logger.warning("No snapshot for %s under %s, skipping", source, source_dir)
            continue
        logger.info(
            "Loaded %s rows from %s (%s snapshot(s), newest %s)",
            df.count(),
            source,
            len(snapshots),
            snapshots[-1].stem,
        )
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


def consolidate_catalogue(data_dir: Path, run_date: str) -> Path | None:
    """Consolidate every season at once, rather than one season at a time.

    Fetching is per season because that is how the upstream APIs are shaped, but
    entity resolution is not a per-season question: a show is one entity, and the
    sources do not always agree which season it belongs to. Kitsu placed nine live
    titles in Summer 2026 that MAL placed in Spring 2026, so each pair sat in a
    different partition and no per-partition merge could ever collapse them. They
    were visible as duplicates on the site for exactly that reason.

    Writing one output for the whole catalogue also keeps `anime_media_latest`
    unambiguous: with per-partition outputs at the same run_date, a title that
    moved between partitions had two rows with equal run_date and no tiebreak.
    """
    spark = get_spark_session("weebblade-consolidate")
    frames: list[DataFrame] = []

    for source, dir_name in SOURCE_DIR_NAMES.items():
        base = data_dir / "processed" / dir_name
        if not base.is_dir():
            logger.warning("No data at all for %s, skipping", source)
            continue
        for partition_dir in sorted(p for p in base.iterdir() if p.is_dir()):
            df = _current_state(spark, partition_dir, run_date)
            if df is None:
                continue
            logger.info("Loaded %s rows from %s/%s", df.count(), source, partition_dir.name)
            frames.append(df)

    if not frames:
        logger.warning("No source data available at all - nothing to consolidate")
        spark.stop()
        return None

    consolidated = frames[0]
    for df in frames[1:]:
        consolidated = consolidated.unionByName(df)

    before = consolidated.count()
    consolidated = _merge_sources(consolidated).withColumn("run_date", F.lit(run_date))
    logger.info("Merged %s source rows into %s titles", before, consolidated.count())

    consolidated = _stamp_identities(spark, consolidated, data_dir, run_date)

    out_dir = data_dir / "processed" / "anime_media_consolidated" / "_catalogue" / run_date
    consolidated.coalesce(1).write.mode("overwrite").parquet(str(out_dir))
    logger.info("Wrote consolidated catalogue to %s", out_dir)

    spark.stop()
    return out_dir


def _stamp_identities(spark, df: DataFrame, data_dir: Path, run_date: str) -> DataFrame:
    """Give every merged title its stable WeebBlade identity.

    The assignment itself is plain Python over a few hundred rows (see
    processing/identity.py) - the catalogue is small, the logic is branchy, and
    keeping it out of Spark is what makes it testable on a machine without a
    JVM. Spark only does the join back.

    The registry is saved BEFORE the catalogue is written. If the write then
    fails, the identities minted this run are already on record and the retry
    reuses them rather than minting a second set.
    """
    rows = df.select("source", "source_id", _SOURCE_KEYS).collect()
    groups = [list(r[_SOURCE_KEYS]) for r in rows]

    ids, registry, report = identity.assign(groups, identity.load(data_dir), run_date)
    path = identity.save(data_dir, registry)
    logger.info("Identities for %s titles: %s (registry %s)", len(ids), report, path)

    mapping = spark.createDataFrame(
        [(r["source"], r["source_id"], wb_id) for r, wb_id in zip(rows, ids)],
        "source string, source_id string, wb_id string",
    )
    # (source, source_id) is unique per merged row - each is the winner of exactly
    # one group - so this join cannot fan out.
    return df.join(mapping, ["source", "source_id"], "left")


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
    4. display title + exact premiere date, for pairs the sources file under
       different formats - `special` against `ONA` for the Re:Zero break-time
       shorts. See `_premiere_key`; this is the one pass that does not use format,
       because format is the very thing being disagreed about.

    Passes 2 and 3 are deliberately narrow. Each requires an exact (case- and
    whitespace-insensitive) title AND the same format AND the same start year, so
    a false merge needs two different shows sharing all three. A false merge
    silently deletes a title, which is worse than the duplicate it prevents, so
    anything less certain than that - fuzzy distance, substring, title without
    format - is left alone.

    The year does the work that season scoping used to. This runs over the whole
    catalogue now (see `consolidate_catalogue`), because sources disagree about
    which season a title starts in and a season-scoped merge could never see both
    halves of such a pair.

    The merge is per-column, taking the first non-null value in source-priority
    order, so one output row holds Kitsu's streaming links and MAL's studios at
    once.

    Every output row also carries `source_keys`: the source:source_id of every
    input row that collapsed into it. The merge picks one winner per column, but
    identity needs all of them - a title must keep its address when a different
    member wins next week, and the only way to know it is the same title is to
    know every key it was ever made of. See processing/identity.py.
    """
    df = df.withColumn(
        _SOURCE_KEYS, F.array(F.concat_ws(":", F.col("source"), F.col("source_id")))
    )
    matched_by_id = _merge_on(
        df,
        F.when(F.col("mal_id").isNotNull(), F.concat(F.lit("mal:"), F.col("mal_id"))).otherwise(
            _identity_key()
        ),
    )
    display_title = F.coalesce(F.col("title_english"), F.col("title_romaji"))
    matched_by_romaji = _merge_on(matched_by_id, _title_key("tr:", F.col("title_romaji")))
    matched_by_title = _merge_on(matched_by_romaji, _title_key("td:", display_title))
    return _merge_on(matched_by_title, _premiere_key(display_title))


def _identity_key() -> "F.Column":
    """A key that matches only the row itself, so an unmatchable row survives a
    pass untouched instead of grouping with every other unmatchable row."""
    return F.concat(F.lit("src:"), F.col("source"), F.lit(":"), F.col("source_id"))


def _title_key(prefix: str, title: "F.Column") -> "F.Column":
    """Case- and whitespace-insensitive title + format + start year, or the row's
    own identity when any part is missing.

    The year is what lets this run over the whole catalogue instead of one season.
    Sources disagree about which season a title starts in - Kitsu calls nine live
    titles Summer 2026 that MAL calls Spring 2026 - so a season-scoped merge can
    never see both halves. They do agree on the year, and requiring it keeps the
    pass from collapsing two unrelated shows that share a name across years, which
    is a real hazard for the generic titles common to music videos and specials.
    """
    return F.when(
        title.isNotNull() & F.col("format").isNotNull() & F.col("season_year").isNotNull(),
        F.concat(
            F.lit(prefix),
            F.lower(F.trim(title)),
            F.lit("|"),
            F.lower(F.col("format")),
            F.lit("|"),
            F.col("season_year").cast("string"),
        ),
    ).otherwise(_identity_key())


def _premiere_key(title: "F.Column") -> "F.Column":
    """Exact title + exact premiere date, with no format at all.

    The other title passes require the format to match, which is what stops a
    series and its compilation film from collapsing into one row. But the sources
    disagree about format for shows that sit between categories: MAL calls the
    Re:Zero break-time shorts `special` where Kitsu calls them `ONA`, and there
    are eight such live pairs, mostly ONA against TV, special or music.

    A same-day premiere under an identical title is strong enough evidence to
    stand without the format, and stronger than format would be: two different
    works sharing a title in one year almost never share a release date, while
    two catalogues describing one work almost always do. Measured over 480 live
    titles this key produces exactly five groups, every one a Kitsu row paired
    with its MAL twin, and no two rows from the same source ever collide.

    All three date parts are required. A partial date would match far too much.
    The three pairs where the sources disagree on the date as well as the format
    are left alone - by one to four days, which a window could bridge, but not
    without weakening the key for every other title.
    """
    complete_date = (
        F.col("start_year").isNotNull()
        & F.col("start_month").isNotNull()
        & F.col("start_day").isNotNull()
    )
    return F.when(
        title.isNotNull() & complete_date,
        F.concat(
            F.lit("tp:"),
            F.lower(F.trim(title)),
            F.lit("|"),
            F.col("start_year").cast("string"),
            F.lit("-"),
            F.col("start_month").cast("string"),
            F.lit("-"),
            F.col("start_day").cast("string"),
        ),
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

    def aggregate(name: str) -> "F.Column":
        # Every other column takes one winner. source_keys takes the union: it is
        # the record of which rows became this one, and dropping all but the
        # winner's would lose exactly what identity needs to recognise the title
        # when a different member wins. Sorted so the result is deterministic.
        if name == _SOURCE_KEYS:
            return F.array_sort(
                F.array_distinct(F.flatten(F.collect_list(F.col(name)).over(window)))
            ).alias(name)
        return F.first(meaningful(name), ignorenulls=True).over(window).alias(name)

    columns = [c for c in df.columns if c not in ("_key", "_priority")]
    merged = df.select(F.col("_key"), *[aggregate(c) for c in columns])
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
